from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from api_server.secret_source import read_secret_setting


ALLOWED_ROLES = frozenset({
    "admin",
    "credential_admin",
    "verification_writer",
    "billing_writer",
    "audit_anchor_operator",
    "reviewer",
    "publisher",
    "experiment_operator",
    "planner",
    "release_manager",
    "rollout_operator",
    "incident_manager",
    "reader",
})


@dataclass(frozen=True)
class ServicePrincipal:
    subject: str
    roles: frozenset[str]
    credential_id: str | None = None
    auth_method: str = "static"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _auth_mode() -> str:
    mode = os.getenv("SERVICE_AUTH_MODE", "jwt").strip().lower()
    if mode not in {"jwt", "static", "hybrid"}:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service auth mode is invalid",
        )
    return mode


def _configured_identities() -> dict[str, dict]:
    raw = read_secret_setting("SERVICE_IDENTITIES_JSON")
    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service identity configuration is invalid",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service identity configuration is invalid",
        )
    return data


def _jwt_keys() -> dict[str, str]:
    raw = read_secret_setting("SERVICE_JWT_KEYS_JSON")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service signing keys are not configured",
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service signing key configuration is invalid",
        ) from exc

    if (
        not isinstance(data, dict)
        or not data
        or not all(
            isinstance(kid, str)
            and kid
            and isinstance(secret_value, str)
            and len(secret_value) >= 32
            for kid, secret_value in data.items()
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service signing key configuration is invalid",
        )

    return data


def _active_kid() -> str:
    kid = os.getenv("SERVICE_JWT_ACTIVE_KID", "").strip()
    keys = _jwt_keys()
    if not kid or kid not in keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="active service signing key is invalid",
        )
    return kid


def _issuer() -> str:
    return os.getenv(
        "SERVICE_JWT_ISSUER",
        "creator-revenue-agent",
    ).strip()


def _audience() -> str:
    return os.getenv(
        "SERVICE_JWT_AUDIENCE",
        "creator-revenue-agent-internal",
    ).strip()


def _max_ttl_seconds() -> int:
    raw = os.getenv("SERVICE_JWT_MAX_TTL_SECONDS", "900")
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service credential TTL configuration is invalid",
        ) from exc
    if value < 60 or value > 3600:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service credential TTL configuration is invalid",
        )
    return value


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signed service credential",
        ) from exc


def _json_segment(data: dict) -> str:
    payload = json.dumps(
        data,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _b64url_encode(payload)


def _encode_jwt(
    *,
    key_id: str,
    secret_value: str,
    payload: dict,
) -> str:
    header = {
        "alg": "HS256",
        "kid": key_id,
        "typ": "JWT",
    }
    header_segment = _json_segment(header)
    payload_segment = _json_segment(payload)
    signing_input = (
        f"{header_segment}.{payload_segment}".encode("ascii")
    )
    signature = hmac.new(
        secret_value.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    return (
        f"{header_segment}.{payload_segment}."
        f"{_b64url_encode(signature)}"
    )


def _decode_json_segment(segment: str) -> dict:
    try:
        value = json.loads(
            _b64url_decode(segment).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signed service credential",
        ) from exc

    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signed service credential",
        )
    return value


def _authenticate_jwt(token: str) -> ServicePrincipal:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signed service credential",
        )

    header = _decode_json_segment(parts[0])
    payload = _decode_json_segment(parts[1])

    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unsupported service credential algorithm",
        )

    key_id = header.get("kid")
    if not isinstance(key_id, str) or not key_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service credential key id is missing",
        )

    keys = _jwt_keys()
    secret_value = keys.get(key_id)
    if secret_value is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service credential signing key is not active",
        )

    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected_signature = hmac.new(
        secret_value.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    supplied_signature = _b64url_decode(parts[2])
    if not hmac.compare_digest(
        supplied_signature,
        expected_signature,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signed service credential",
        )

    subject = payload.get("sub")
    roles = payload.get("roles")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    credential_id = payload.get("jti")
    issuer = payload.get("iss")
    audience = payload.get("aud")

    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(credential_id, str)
        or not credential_id
        or not isinstance(roles, list)
        or not roles
        or not all(
            isinstance(role, str)
            and role in ALLOWED_ROLES
            for role in roles
        )
        or not isinstance(issued_at, int)
        or not isinstance(expires_at, int)
        or issuer != _issuer()
        or audience != _audience()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid signed service credential claims",
        )

    now = int(time.time())
    if issued_at > now + 30 or expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service credential expired or not yet valid",
        )
    if (
        expires_at <= issued_at
        or expires_at - issued_at > _max_ttl_seconds()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="service credential lifetime is invalid",
        )

    if _bool_env(
        "SERVICE_JWT_REQUIRE_ISSUED_RECORD",
        True,
    ):
        from api_server.db import (
            IssuedCredentialRecord,
            SessionLocal,
        )

        with SessionLocal() as session:
            record = session.get(
                IssuedCredentialRecord,
                credential_id,
            )
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="service credential is not recognized",
                )
            if record.revoked_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="service credential has been revoked",
                )
            stored_roles = json.loads(record.roles_json)
            stored_expires_at = record.expires_at
            if stored_expires_at.tzinfo is None:
                stored_expires_at = stored_expires_at.replace(
                    tzinfo=timezone.utc
                )
            stored_issued_at = record.issued_at
            if stored_issued_at.tzinfo is None:
                stored_issued_at = stored_issued_at.replace(
                    tzinfo=timezone.utc
                )

            if (
                record.subject != subject
                or record.key_id != key_id
                or sorted(stored_roles) != sorted(roles)
                or int(stored_issued_at.timestamp()) != issued_at
                or int(stored_expires_at.timestamp()) != expires_at
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="service credential registry mismatch",
                )

    return ServicePrincipal(
        subject=subject,
        roles=frozenset(roles),
        credential_id=credential_id,
        auth_method="jwt",
    )


def _authenticate_static(token: str) -> ServicePrincipal | None:
    identities = _configured_identities()
    for subject, config in identities.items():
        if not isinstance(subject, str) or not isinstance(config, dict):
            continue

        configured_token = config.get("token")
        roles = config.get("roles", [])
        if not isinstance(configured_token, str) or not configured_token:
            continue
        if not isinstance(roles, list) or not all(
            isinstance(role, str)
            and role in ALLOWED_ROLES
            for role in roles
        ):
            continue

        if secrets.compare_digest(token, configured_token):
            return ServicePrincipal(
                subject=subject,
                roles=frozenset(roles),
                auth_method="static",
            )

    if _bool_env("ALLOW_LEGACY_ADMIN_TOKEN", False):
        expected = (
            read_secret_setting("INTERNAL_API_TOKEN")
            or read_secret_setting("CUSTOM_API_TOKEN")
        )
        if (
            expected
            and secrets.compare_digest(token, expected)
        ):
            return ServicePrincipal(
                subject="legacy-admin",
                roles=frozenset({"admin"}),
                auth_method="legacy",
            )

    return None


def _authenticate(
    authorization: str | None,
) -> ServicePrincipal:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
        )

    supplied = authorization.removeprefix("Bearer ").strip()
    if not supplied:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
        )

    mode = _auth_mode()

    if mode in {"jwt", "hybrid"} and supplied.count(".") == 2:
        return _authenticate_jwt(supplied)

    if mode in {"static", "hybrid"}:
        principal = _authenticate_static(supplied)
        if principal is not None:
            return principal

    if mode == "jwt" and not os.getenv(
        "SERVICE_JWT_KEYS_JSON",
        "",
    ).strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service signing keys are not configured",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid bearer token",
    )


def require_service_token(
    authorization: str | None = Header(default=None),
) -> ServicePrincipal:
    return _authenticate(authorization)


def require_roles(
    *required_roles: str,
) -> Callable[..., ServicePrincipal]:
    required = frozenset(required_roles)

    def dependency(
        authorization: str | None = Header(default=None),
    ) -> ServicePrincipal:
        principal = _authenticate(authorization)
        if (
            "admin" not in principal.roles
            and required.isdisjoint(principal.roles)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient service role",
            )
        return principal

    return dependency


def issue_service_credential(
    session: Session,
    *,
    issuer_principal: ServicePrincipal,
    subject: str,
    roles: list[str],
    ttl_seconds: int,
):
    from api_server.db import IssuedCredentialRecord
    from api_server.schemas import CredentialResponse

    normalized_roles = sorted(set(roles))
    if (
        not normalized_roles
        or any(
            role not in ALLOWED_ROLES
            for role in normalized_roles
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid service roles",
        )

    privileged = {"admin", "credential_admin"}
    if (
        privileged.intersection(normalized_roles)
        and "admin" not in issuer_principal.roles
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role required to issue privileged credentials",
        )

    max_ttl = _max_ttl_seconds()
    if ttl_seconds < 60 or ttl_seconds > max_ttl:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ttl_seconds must be between 60 and {max_ttl}",
        )

    key_id = _active_kid()
    secret_value = _jwt_keys()[key_id]
    issued_timestamp = int(time.time())
    expires_timestamp = issued_timestamp + ttl_seconds
    credential_id = f"cred_{uuid4().hex}"

    payload = {
        "aud": _audience(),
        "exp": expires_timestamp,
        "iat": issued_timestamp,
        "iss": _issuer(),
        "jti": credential_id,
        "roles": normalized_roles,
        "sub": subject,
    }
    token = _encode_jwt(
        key_id=key_id,
        secret_value=secret_value,
        payload=payload,
    )

    record = IssuedCredentialRecord(
        id=credential_id,
        subject=subject,
        roles_json=json.dumps(
            normalized_roles,
            separators=(",", ":"),
        ),
        key_id=key_id,
        issued_by=issuer_principal.subject,
        issued_at=datetime.fromtimestamp(
            issued_timestamp,
            tz=timezone.utc,
        ),
        expires_at=datetime.fromtimestamp(
            expires_timestamp,
            tz=timezone.utc,
        ),
    )
    session.add(record)
    session.commit()
    session.refresh(record)

    return CredentialResponse(
        credential_id=record.id,
        subject=record.subject,
        roles=normalized_roles,
        key_id=record.key_id,
        token_type="Bearer",
        access_token=token,
        issued_at=record.issued_at,
        expires_at=record.expires_at,
    )


def get_credential_status(
    session: Session,
    *,
    credential_id: str,
):
    from api_server.db import IssuedCredentialRecord
    from api_server.schemas import CredentialStatusResponse

    record = session.get(IssuedCredentialRecord, credential_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service credential not found",
        )

    now = datetime.now(timezone.utc)
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return CredentialStatusResponse(
        credential_id=record.id,
        subject=record.subject,
        roles=json.loads(record.roles_json),
        key_id=record.key_id,
        issued_by=record.issued_by,
        issued_at=record.issued_at,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        revoked_by=record.revoked_by,
        revoke_reason=record.revoke_reason,
        active=(
            record.revoked_at is None
            and expires_at > now
        ),
    )


def revoke_service_credential(
    session: Session,
    *,
    credential_id: str,
    revoked_by: str,
    reason: str,
):
    from api_server.db import IssuedCredentialRecord

    record = session.get(IssuedCredentialRecord, credential_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service credential not found",
        )

    if record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        record.revoked_by = revoked_by
        record.revoke_reason = reason
        session.commit()
        session.refresh(record)

    return get_credential_status(
        session,
        credential_id=credential_id,
    )


def get_signing_key_status():
    from api_server.schemas import SigningKeyStatusResponse

    keys = _jwt_keys()
    return SigningKeyStatusResponse(
        active_key_id=_active_kid(),
        configured_key_ids=sorted(keys),
        auth_mode=_auth_mode(),
        max_ttl_seconds=_max_ttl_seconds(),
    )
