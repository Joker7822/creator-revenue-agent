from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from api_server.audit_anchor import audit_anchor_freshness
from api_server.audit_integrity import (
    audit_hash_configuration_status,
    verify_audit_chain,
)
from api_server.db import production_database_locking_status
from api_server.auth import get_signing_key_status
from api_server.migration_runtime import (
    current_revision,
    head_revision,
)
from api_server.schemas import (
    ProductionReadinessCheck,
    ProductionReadinessResponse,
)
from api_server.verification import trusted_verification_required
from api_server.verification_webhooks import get_webhook_key_status


def _check(
    name: str,
    ready: bool,
    detail: str,
) -> ProductionReadinessCheck:
    return ProductionReadinessCheck(
        name=name,
        ready=ready,
        detail=detail,
    )


def _safe_check(
    name: str,
    function,
) -> ProductionReadinessCheck:
    try:
        ready, detail = function()
        return _check(name, ready, detail)
    except HTTPException as exc:
        return _check(
            name,
            False,
            str(exc.detail),
        )
    except Exception as exc:
        return _check(
            name,
            False,
            f"{type(exc).__name__}",
        )


def production_readiness(
    session: Session,
) -> ProductionReadinessResponse:
    checks: list[ProductionReadinessCheck] = []

    def database_check() -> tuple[bool, str]:
        current = current_revision()
        head = head_revision()
        return (
            current == head,
            f"current={current!r}, head={head!r}",
        )

    checks.append(
        _safe_check(
            "database_revision",
            database_check,
        )
    )

    checks.append(
        _safe_check(
            "database_concurrency",
            production_database_locking_status,
        )
    )

    def auth_check() -> tuple[bool, str]:
        status = get_signing_key_status()
        return (
            status.auth_mode == "jwt",
            (
                f"auth_mode={status.auth_mode}; "
                f"active_key_id={status.active_key_id}"
            ),
        )

    checks.append(
        _safe_check(
            "service_authentication",
            auth_check,
        )
    )

    checks.append(
        _check(
            "trusted_verification",
            trusted_verification_required(),
            (
                "REQUIRE_TRUSTED_VERIFICATION=true"
                if trusted_verification_required()
                else "REQUIRE_TRUSTED_VERIFICATION=false"
            ),
        )
    )

    def webhook_check() -> tuple[bool, str]:
        status = get_webhook_key_status()
        provider_count = len(status.providers)
        ready = (
            status.key_id_required
            and provider_count > 0
            and all(status.providers.values())
        )
        return (
            ready,
            (
                f"key_id_required={status.key_id_required}; "
                f"providers={provider_count}"
            ),
        )

    checks.append(
        _safe_check(
            "verification_webhook_keys",
            webhook_check,
        )
    )

    def audit_key_check() -> tuple[bool, str]:
        return audit_hash_configuration_status()

    checks.append(
        _safe_check(
            "audit_hmac_keys",
            audit_key_check,
        )
    )

    def audit_chain_check() -> tuple[bool, str]:
        result = verify_audit_chain(session)
        return (
            result.valid,
            (
                "valid"
                if result.valid
                else f"invalid:{result.reason}"
            ),
        )

    checks.append(
        _safe_check(
            "audit_chain_integrity",
            audit_chain_check,
        )
    )

    def anchor_check() -> tuple[bool, str]:
        result = audit_anchor_freshness(session)
        return (
            result.fresh,
            (
                f"status={result.verification_status}; "
                f"age_seconds={result.age_seconds}; "
                f"unanchored_events={result.unanchored_events}; "
                f"reason={result.reason}"
            ),
        )

    checks.append(
        _safe_check(
            "audit_anchor_freshness",
            anchor_check,
        )
    )

    return ProductionReadinessResponse(
        ready=all(check.ready for check in checks),
        checks=checks,
    )
