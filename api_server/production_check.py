from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass

from api_server.secret_source import read_secret_setting


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _check(
    name: str,
    condition: bool,
    detail: str,
) -> Check:
    return Check(name=name, ok=condition, detail=detail)


def _json_secret(
    name: str,
) -> tuple[bool, str, object | None]:
    try:
        raw = read_secret_setting(name)
    except Exception as exc:
        return (
            False,
            str(getattr(exc, "detail", exc)),
            None,
        )

    if not raw:
        return False, "missing", None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False, "invalid JSON", None

    source = (
        f"{name}_FILE"
        if os.getenv(f"{name}_FILE")
        else name
    )
    return True, f"source={source}", parsed


def _secret_absent(name: str) -> tuple[bool, str]:
    try:
        value = read_secret_setting(name)
    except Exception as exc:
        return (
            False,
            str(getattr(exc, "detail", exc)),
        )
    return (
        not bool(value),
        "unset" if not value else "configured",
    )


def production_configuration_checks() -> list[Check]:
    checks: list[Check] = []

    app_env = os.getenv("APP_ENV", "").strip().lower()
    checks.append(
        _check(
            "app_env",
            app_env == "production",
            f"APP_ENV={app_env or '<unset>'}",
        )
    )

    try:
        database_url = read_secret_setting("DATABASE_URL")
    except Exception as exc:
        database_url = ""
        checks.append(
            _check(
                "database_url_source",
                False,
                str(getattr(exc, "detail", exc)),
            )
        )
    checks.append(
        _check(
            "database_url",
            database_url.startswith(
                ("postgresql://", "postgresql+psycopg://")
            ),
            "PostgreSQL required",
        )
    )

    checks.extend(
        [
            _check(
                "row_locking_required",
                _bool(
                    "PRODUCTION_REQUIRE_ROW_LOCKING_DATABASE",
                    True,
                ),
                "must be true",
            ),
            _check(
                "human_review_required",
                _bool("REQUIRE_HUMAN_REVIEW", True),
                "must be true",
            ),
            _check(
                "auto_publish_disabled",
                not _bool("ALLOW_AUTO_PUBLISH", False),
                "must be false",
            ),
            _check(
                "legacy_admin_disabled",
                not _bool("ALLOW_LEGACY_ADMIN_TOKEN", False),
                "must be false",
            ),
            _check(
                "jwt_only_auth",
                os.getenv(
                    "SERVICE_AUTH_MODE",
                    "",
                ).strip().lower()
                == "jwt",
                "SERVICE_AUTH_MODE must be jwt",
            ),
            _check(
                "static_identities_absent",
                _secret_absent(
                    "SERVICE_IDENTITIES_JSON"
                )[0],
                _secret_absent(
                    "SERVICE_IDENTITIES_JSON"
                )[1],
            ),
            _check(
                "legacy_tokens_absent",
                (
                    _secret_absent(
                        "INTERNAL_API_TOKEN"
                    )[0]
                    and _secret_absent(
                        "CUSTOM_API_TOKEN"
                    )[0]
                ),
                (
                    "INTERNAL_API_TOKEN="
                    + _secret_absent(
                        "INTERNAL_API_TOKEN"
                    )[1]
                    + "; CUSTOM_API_TOKEN="
                    + _secret_absent(
                        "CUSTOM_API_TOKEN"
                    )[1]
                ),
            ),
            _check(
                "issued_record_required",
                _bool(
                    "SERVICE_JWT_REQUIRE_ISSUED_RECORD",
                    True,
                ),
                "must be true",
            ),
            _check(
                "trusted_verification_required",
                _bool(
                    "REQUIRE_TRUSTED_VERIFICATION",
                    True,
                ),
                "must be true",
            ),
            _check(
                "webhook_key_id_required",
                _bool(
                    "VERIFICATION_WEBHOOK_REQUIRE_KEY_ID",
                    True,
                ),
                "must be true",
            ),
            _check(
                "anchor_freshness_enforced",
                _bool(
                    "ENFORCE_AUDIT_ANCHOR_FRESHNESS_ON_ROLLOUT",
                    True,
                ),
                "must be true",
            ),
        ]
    )

    parsed_secrets: dict[str, object] = {}
    for secret_name in (
        "SERVICE_JWT_KEYS_JSON",
        "VERIFICATION_WEBHOOK_KEYS_JSON",
        "AUDIT_HASH_KEYS_JSON",
        "AUDIT_ANCHOR_RECEIPT_KEYS_JSON",
    ):
        ok, detail, parsed = _json_secret(secret_name)
        if ok and not isinstance(parsed, dict):
            ok = False
            detail = "JSON object required"
        if ok and isinstance(parsed, dict) and not parsed:
            ok = False
            detail = "non-empty JSON object required"
        checks.append(
            _check(
                f"secret:{secret_name}",
                ok,
                detail,
            )
        )
        if ok:
            parsed_secrets[secret_name] = parsed

    try:
        anchor_token = read_secret_setting("AUDIT_ANCHOR_TOKEN")
        anchor_token_ok = bool(anchor_token)
        anchor_token_detail = (
            "source=AUDIT_ANCHOR_TOKEN_FILE"
            if os.getenv("AUDIT_ANCHOR_TOKEN_FILE")
            else "source=AUDIT_ANCHOR_TOKEN"
        )
    except Exception as exc:
        anchor_token_ok = False
        anchor_token_detail = str(
            getattr(exc, "detail", exc)
        )
    checks.append(
        _check(
            "secret:AUDIT_ANCHOR_TOKEN",
            anchor_token_ok,
            anchor_token_detail,
        )
    )

    jwt_keys = parsed_secrets.get("SERVICE_JWT_KEYS_JSON")
    active_jwt_kid = os.getenv(
        "SERVICE_JWT_ACTIVE_KID",
        "",
    ).strip()
    checks.append(
        _check(
            "active_jwt_key",
            isinstance(jwt_keys, dict)
            and active_jwt_kid in jwt_keys,
            f"active_key_id={active_jwt_kid or '<unset>'}",
        )
    )

    audit_keys = parsed_secrets.get("AUDIT_HASH_KEYS_JSON")
    active_audit_kid = os.getenv(
        "AUDIT_HASH_ACTIVE_KID",
        "",
    ).strip()
    checks.append(
        _check(
            "active_audit_key",
            isinstance(audit_keys, dict)
            and active_audit_kid in audit_keys,
            f"active_key_id={active_audit_kid or '<unset>'}",
        )
    )

    def bounded_int(
        name: str,
        *,
        minimum: int,
        maximum: int,
        default: int,
    ) -> tuple[bool, str]:
        raw = os.getenv(name, str(default))
        try:
            value = int(raw)
        except ValueError:
            return False, "invalid integer"
        return (
            minimum <= value <= maximum,
            f"value={value}; allowed={minimum}..{maximum}",
        )

    for check_name, env_name, minimum, maximum, default in (
        (
            "request_body_limit",
            "MAX_REQUEST_BODY_BYTES",
            1024,
            4_194_304,
            1_048_576,
        ),
        (
            "billing_rate_limit",
            "BILLING_RATE_LIMIT_PER_MINUTE",
            1,
            10_000,
            120,
        ),
        (
            "credential_rate_limit",
            "CREDENTIAL_RATE_LIMIT_PER_MINUTE",
            1,
            1_000,
            30,
        ),
        (
            "rollout_rate_limit",
            "ROLLOUT_RATE_LIMIT_PER_MINUTE",
            1,
            1_000,
            30,
        ),
        (
            "verification_webhook_rate_limit",
            "VERIFICATION_WEBHOOK_RATE_LIMIT_PER_MINUTE",
            1,
            50_000,
            300,
        ),
    ):
        ok, detail = bounded_int(
            env_name,
            minimum=minimum,
            maximum=maximum,
            default=default,
        )
        checks.append(_check(check_name, ok, detail))

    metrics_export_mode = os.getenv(
        "METRICS_EXPORT_MODE",
        "",
    ).strip().lower()
    checks.append(
        _check(
            "metrics_export_mode",
            metrics_export_mode == "prometheus",
            (
                "METRICS_EXPORT_MODE must be prometheus"
            ),
        )
    )

    edge_rate_limit_mode = os.getenv(
        "EDGE_RATE_LIMIT_MODE",
        "",
    ).strip().lower()
    checks.append(
        _check(
            "edge_rate_limit_mode",
            edge_rate_limit_mode == "external",
            (
                "EDGE_RATE_LIMIT_MODE must be external"
            ),
        )
    )

    anchor_url = os.getenv(
        "AUDIT_ANCHOR_BASE_URL",
        "",
    ).strip()
    checks.append(
        _check(
            "audit_anchor_tls",
            anchor_url.startswith("https://"),
            "HTTPS required",
        )
    )

    return checks


def main() -> int:
    checks = production_configuration_checks()
    payload = {
        "ready": all(check.ok for check in checks),
        "checks": [asdict(check) for check in checks],
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
