from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from typing import Callable

from fastapi import Header, HTTPException, status


@dataclass(frozen=True)
class ServicePrincipal:
    subject: str
    roles: frozenset[str]


def _configured_identities() -> dict[str, dict]:
    raw = os.getenv("SERVICE_IDENTITIES_JSON", "").strip()
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

    identities = _configured_identities()
    for subject, config in identities.items():
        if not isinstance(subject, str) or not isinstance(config, dict):
            continue

        token = config.get("token")
        roles = config.get("roles", [])
        if not isinstance(token, str) or not token:
            continue
        if not isinstance(roles, list) or not all(
            isinstance(role, str) and role
            for role in roles
        ):
            continue

        if secrets.compare_digest(supplied, token):
            return ServicePrincipal(
                subject=subject,
                roles=frozenset(roles),
            )

    allow_legacy = os.getenv(
        "ALLOW_LEGACY_ADMIN_TOKEN",
        "false",
    ).lower() in {"1", "true", "yes", "on"}

    if allow_legacy:
        expected = (
            os.getenv("INTERNAL_API_TOKEN")
            or os.getenv("CUSTOM_API_TOKEN")
        )
        if (
            expected
            and secrets.compare_digest(supplied, expected)
        ):
            return ServicePrincipal(
                subject="legacy-admin",
                roles=frozenset({"admin"}),
            )

    if not identities and not allow_legacy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service identities are not configured",
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
