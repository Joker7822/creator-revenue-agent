from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api_server.db import (
    VerificationRecord,
    VerificationWebhookEventRecord,
)
from api_server.secret_source import read_secret_setting
from api_server.schemas import (
    VerificationResponse,
    VerificationWebhookKeyStatusResponse,
    VerificationWebhookPayload,
    VerificationWebhookResponse,
)
from api_server.verification import (
    create_verification_record,
    revoke_verification_record,
)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _validate_provider_keys(data: object) -> dict[str, dict[str, str]]:
    if not isinstance(data, dict) or not data:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verification webhook key configuration is invalid",
        )

    result: dict[str, dict[str, str]] = {}
    for provider, keys in data.items():
        if (
            not isinstance(provider, str)
            or not provider
            or len(provider) > 120
            or not isinstance(keys, dict)
            or not keys
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="verification webhook key configuration is invalid",
            )

        normalized: dict[str, str] = {}
        for key_id, secret_value in keys.items():
            if (
                not isinstance(key_id, str)
                or not key_id
                or len(key_id) > 120
                or not isinstance(secret_value, str)
                or len(secret_value) < 32
            ):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="verification webhook key configuration is invalid",
                )
            normalized[key_id] = secret_value
        result[provider] = normalized

    return result


def _provider_keys() -> dict[str, dict[str, str]]:
    raw = read_secret_setting(
        "VERIFICATION_WEBHOOK_KEYS_JSON",
    )
    if raw:
        try:
            return _validate_provider_keys(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="verification webhook key configuration is invalid",
            ) from exc

    legacy_raw = read_secret_setting(
        "VERIFICATION_WEBHOOK_SECRETS_JSON",
    )
    if not legacy_raw:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verification webhook keys are not configured",
        )

    try:
        legacy = json.loads(legacy_raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verification webhook secret configuration is invalid",
        ) from exc

    if (
        not isinstance(legacy, dict)
        or not legacy
        or not all(
            isinstance(provider, str)
            and provider
            and len(provider) <= 120
            and isinstance(secret_value, str)
            and len(secret_value) >= 32
            for provider, secret_value in legacy.items()
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verification webhook secret configuration is invalid",
        )

    return {
        provider: {"legacy": secret_value}
        for provider, secret_value in legacy.items()
    }


def _require_key_id() -> bool:
    return _bool_env(
        "VERIFICATION_WEBHOOK_REQUIRE_KEY_ID",
        True,
    )


def get_webhook_key_status() -> VerificationWebhookKeyStatusResponse:
    keys = _provider_keys()
    return VerificationWebhookKeyStatusResponse(
        key_id_required=_require_key_id(),
        providers={
            provider: sorted(provider_keys)
            for provider, provider_keys in sorted(keys.items())
        },
    )


def _max_age_seconds() -> int:
    raw = os.getenv(
        "VERIFICATION_WEBHOOK_MAX_AGE_SECONDS",
        "300",
    )
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verification webhook replay window is invalid",
        ) from exc
    if value < 30 or value > 3600:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verification webhook replay window is invalid",
        )
    return value


def _max_body_bytes() -> int:
    raw = os.getenv(
        "VERIFICATION_WEBHOOK_MAX_BODY_BYTES",
        "65536",
    )
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verification webhook body limit is invalid",
        ) from exc
    if value < 1024 or value > 1_048_576:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="verification webhook body limit is invalid",
        )
    return value


def _verification_response(
    record: VerificationRecord,
) -> VerificationResponse:
    return VerificationResponse(
        verification_id=record.id,
        subject_ref=record.subject_ref,
        kind=record.kind,
        status=record.status,
        source=record.source,
        source_record_ref=record.source_record_ref,
        age_years=record.age_years,
        created_by=record.created_by,
        created_at=record.created_at,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        revoked_by=record.revoked_by,
        revoke_reason=record.revoke_reason,
    )


def _parse_timestamp(timestamp_value: str) -> int:
    try:
        timestamp = int(timestamp_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid webhook timestamp",
        ) from exc

    now = int(time.time())
    if abs(now - timestamp) > _max_age_seconds():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="webhook timestamp outside replay window",
        )
    return timestamp


def _select_key(
    *,
    provider: str,
    key_id: str | None,
) -> tuple[str, str, bool]:
    provider_keys = _provider_keys().get(provider)
    if provider_keys is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unknown verification webhook provider",
        )

    if key_id:
        secret_value = provider_keys.get(key_id)
        if secret_value is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="verification webhook signing key is not active",
            )
        return key_id, secret_value, False

    if _require_key_id():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="verification webhook key id required",
        )

    if len(provider_keys) != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="verification webhook key id required during rotation",
        )

    resolved_key_id, secret_value = next(
        iter(provider_keys.items())
    )
    return resolved_key_id, secret_value, True


def _verify_signature(
    *,
    provider: str,
    key_id: str | None,
    event_id: str,
    timestamp_value: str,
    signature: str,
    body: bytes,
) -> str:
    if len(body) > _max_body_bytes():
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="verification webhook body too large",
        )

    resolved_key_id, secret_value, legacy_canonical = (
        _select_key(
            provider=provider,
            key_id=key_id,
        )
    )

    timestamp = _parse_timestamp(timestamp_value)
    if legacy_canonical:
        canonical = (
            f"{provider}.{timestamp}.{event_id}.".encode(
                "utf-8"
            )
            + body
        )
    else:
        canonical = (
            (
                f"{provider}.{resolved_key_id}."
                f"{timestamp}.{event_id}."
            ).encode("utf-8")
            + body
        )

    expected = hmac.new(
        secret_value.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()

    if not signature.startswith("v1="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="unsupported verification webhook signature version",
        )
    supplied = signature[3:]

    if (
        len(supplied) != 64
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid verification webhook signature",
        )

    return resolved_key_id


def _existing_provider_record(
    session: Session,
    *,
    provider: str,
    payload: VerificationWebhookPayload,
) -> VerificationRecord | None:
    return session.scalar(
        select(VerificationRecord)
        .where(
            VerificationRecord.source == provider,
            VerificationRecord.source_record_ref
            == payload.provider_record_ref,
            VerificationRecord.subject_ref
            == payload.subject_ref,
            VerificationRecord.kind == payload.kind,
        )
        .order_by(VerificationRecord.created_at.desc())
    )


def _duplicate_response(
    event: VerificationWebhookEventRecord,
) -> VerificationWebhookResponse:
    data = json.loads(event.result_json)
    verification = VerificationResponse.model_validate(data)
    return VerificationWebhookResponse(
        provider=event.provider,
        key_id=event.key_id,
        event_id=event.event_id,
        event_type=event.event_type,
        duplicate=True,
        verification=verification,
    )


def process_verification_webhook(
    session: Session,
    *,
    provider: str,
    key_id: str | None,
    event_id: str,
    timestamp_value: str,
    signature: str,
    body: bytes,
) -> VerificationWebhookResponse:
    if not provider or len(provider) > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid verification provider",
        )
    if key_id is not None and (
        not key_id or len(key_id) > 120
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid verification webhook key id",
        )
    if not event_id or len(event_id) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid verification webhook event id",
        )

    resolved_key_id = _verify_signature(
        provider=provider,
        key_id=key_id,
        event_id=event_id,
        timestamp_value=timestamp_value,
        signature=signature,
        body=body,
    )
    body_sha256 = hashlib.sha256(body).hexdigest()

    existing_event = session.scalar(
        select(VerificationWebhookEventRecord).where(
            VerificationWebhookEventRecord.provider == provider,
            VerificationWebhookEventRecord.event_id == event_id,
        )
    )
    if existing_event is not None:
        if existing_event.body_sha256 != body_sha256:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="webhook event id payload conflict",
            )
        return _duplicate_response(existing_event)

    try:
        payload = VerificationWebhookPayload.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid verification webhook payload",
        ) from exc

    actor = f"webhook:{provider}"
    provider_record = _existing_provider_record(
        session,
        provider=provider,
        payload=payload,
    )

    if payload.event_type == "verification.verified":
        if provider_record is not None:
            if provider_record.status == "revoked":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="provider verification reference already revoked",
                )
            verification = provider_record
        else:
            verification = create_verification_record(
                session,
                subject_ref=payload.subject_ref,
                kind=payload.kind,
                source=provider,
                source_record_ref=payload.provider_record_ref,
                age_years=payload.age_years,
                expires_at=payload.expires_at,
                created_by=actor,
            )
    else:
        if provider_record is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="provider verification reference not found",
            )
        verification = revoke_verification_record(
            session,
            record=provider_record,
            actor=actor,
            reason=(
                payload.reason
                or "provider verification revoked"
            ),
        )

    verification_snapshot = _verification_response(
        verification
    )
    event = VerificationWebhookEventRecord(
        id=f"vwh_{uuid4().hex}",
        provider=provider,
        key_id=resolved_key_id,
        event_id=event_id,
        event_type=payload.event_type,
        body_sha256=body_sha256,
        verification_id=verification.id,
        result_json=json.dumps(
            verification_snapshot.model_dump(
                mode="json",
            ),
            separators=(",", ":"),
            sort_keys=True,
        ),
        received_at=datetime.now(timezone.utc),
    )
    session.add(event)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(VerificationWebhookEventRecord).where(
                VerificationWebhookEventRecord.provider == provider,
                VerificationWebhookEventRecord.event_id == event_id,
            )
        )
        if concurrent is None:
            raise
        if concurrent.body_sha256 != body_sha256:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="webhook event id payload conflict",
            )
        return _duplicate_response(concurrent)

    return VerificationWebhookResponse(
        provider=provider,
        key_id=resolved_key_id,
        event_id=event_id,
        event_type=payload.event_type,
        duplicate=False,
        verification=verification_snapshot,
    )
