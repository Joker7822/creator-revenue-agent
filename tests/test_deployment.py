import json

import pytest
from fastapi import HTTPException

from api_server.auth import get_signing_key_status
from api_server.production_check import (
    production_configuration_checks,
)
from api_server.secret_source import read_secret_setting


def test_secret_file_source(
    monkeypatch,
    tmp_path,
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("mounted-secret\n", encoding="utf-8")
    monkeypatch.delenv("TEST_SECRET", raising=False)
    monkeypatch.setenv(
        "TEST_SECRET_FILE",
        str(secret_file),
    )

    assert read_secret_setting("TEST_SECRET") == "mounted-secret"


def test_secret_direct_and_file_conflict_fails_closed(
    monkeypatch,
    tmp_path,
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_text("file-value", encoding="utf-8")
    monkeypatch.setenv("TEST_SECRET", "direct-value")
    monkeypatch.setenv(
        "TEST_SECRET_FILE",
        str(secret_file),
    )

    with pytest.raises(HTTPException) as exc:
        read_secret_setting("TEST_SECRET")

    assert exc.value.status_code == 503
    assert "cannot both be set" in str(exc.value.detail)


def test_jwt_signing_keys_can_come_from_file(
    monkeypatch,
    tmp_path,
) -> None:
    keys = {
        "mounted-kid": "mounted-secret-0000000000000000000000001"
    }
    secret_file = tmp_path / "jwt-keys.json"
    secret_file.write_text(
        json.dumps(keys),
        encoding="utf-8",
    )

    monkeypatch.delenv(
        "SERVICE_JWT_KEYS_JSON",
        raising=False,
    )
    monkeypatch.setenv(
        "SERVICE_JWT_KEYS_JSON_FILE",
        str(secret_file),
    )
    monkeypatch.setenv(
        "SERVICE_JWT_ACTIVE_KID",
        "mounted-kid",
    )

    status = get_signing_key_status()
    assert status.active_key_id == "mounted-kid"
    assert status.configured_key_ids == ["mounted-kid"]


def _write_secret(
    tmp_path,
    name: str,
    value: str,
) -> str:
    path = tmp_path / name.lower()
    path.write_text(value, encoding="utf-8")
    return str(path)


def test_production_configuration_accepts_secret_files(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("SERVICE_IDENTITIES_JSON", raising=False)
    monkeypatch.delenv("SERVICE_IDENTITIES_JSON_FILE", raising=False)
    monkeypatch.delenv("INTERNAL_API_TOKEN", raising=False)
    monkeypatch.delenv("INTERNAL_API_TOKEN_FILE", raising=False)
    monkeypatch.delenv("CUSTOM_API_TOKEN", raising=False)
    monkeypatch.delenv("CUSTOM_API_TOKEN_FILE", raising=False)

    for name in (
        "DATABASE_URL",
        "SERVICE_JWT_KEYS_JSON",
        "VERIFICATION_WEBHOOK_KEYS_JSON",
        "AUDIT_HASH_KEYS_JSON",
        "AUDIT_ANCHOR_TOKEN",
        "AUDIT_ANCHOR_RECEIPT_KEYS_JSON",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv(
        "DATABASE_URL_FILE",
        _write_secret(
            tmp_path,
            "database_url",
            "postgresql+psycopg://app:secret@db/app",
        ),
    )
    monkeypatch.setenv(
        "SERVICE_JWT_KEYS_JSON_FILE",
        _write_secret(
            tmp_path,
            "jwt_keys",
            json.dumps(
                {
                    "jwt-current": (
                        "jwt-secret-0000000000000000000000000001"
                    )
                }
            ),
        ),
    )
    monkeypatch.setenv(
        "VERIFICATION_WEBHOOK_KEYS_JSON_FILE",
        _write_secret(
            tmp_path,
            "webhook_keys",
            json.dumps(
                {
                    "provider-a": {
                        "provider-current": (
                            "provider-secret-00000000000000000001"
                        )
                    }
                }
            ),
        ),
    )
    monkeypatch.setenv(
        "AUDIT_HASH_KEYS_JSON_FILE",
        _write_secret(
            tmp_path,
            "audit_keys",
            json.dumps(
                {
                    "audit-current": (
                        "audit-secret-0000000000000000000000001"
                    )
                }
            ),
        ),
    )
    monkeypatch.setenv(
        "AUDIT_ANCHOR_TOKEN_FILE",
        _write_secret(
            tmp_path,
            "anchor_token",
            "anchor-token-0000000000000000000000000001",
        ),
    )
    monkeypatch.setenv(
        "AUDIT_ANCHOR_RECEIPT_KEYS_JSON_FILE",
        _write_secret(
            tmp_path,
            "receipt_keys",
            json.dumps(
                {
                    "receipt-current": (
                        "receipt-secret-00000000000000000000001"
                    )
                }
            ),
        ),
    )

    monkeypatch.setenv(
        "PRODUCTION_REQUIRE_ROW_LOCKING_DATABASE",
        "true",
    )
    monkeypatch.setenv("REQUIRE_HUMAN_REVIEW", "true")
    monkeypatch.setenv("ALLOW_AUTO_PUBLISH", "false")
    monkeypatch.setenv("ALLOW_LEGACY_ADMIN_TOKEN", "false")
    monkeypatch.setenv("SERVICE_AUTH_MODE", "jwt")
    monkeypatch.setenv(
        "SERVICE_JWT_REQUIRE_ISSUED_RECORD",
        "true",
    )
    monkeypatch.setenv(
        "REQUIRE_TRUSTED_VERIFICATION",
        "true",
    )
    monkeypatch.setenv(
        "VERIFICATION_WEBHOOK_REQUIRE_KEY_ID",
        "true",
    )
    monkeypatch.setenv(
        "ENFORCE_AUDIT_ANCHOR_FRESHNESS_ON_ROLLOUT",
        "true",
    )
    monkeypatch.setenv(
        "SERVICE_JWT_ACTIVE_KID",
        "jwt-current",
    )
    monkeypatch.setenv(
        "AUDIT_HASH_ACTIVE_KID",
        "audit-current",
    )
    monkeypatch.setenv(
        "AUDIT_ANCHOR_BASE_URL",
        "https://anchor.internal.example",
    )

    checks = production_configuration_checks()
    failed = [check for check in checks if not check.ok]
    assert failed == []


def test_production_configuration_rejects_insecure_basics(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unsafe.db")
    monkeypatch.delenv("DATABASE_URL_FILE", raising=False)
    monkeypatch.setenv(
        "AUDIT_ANCHOR_BASE_URL",
        "http://anchor.internal",
    )

    checks = {
        check.name: check
        for check in production_configuration_checks()
    }
    assert checks["app_env"].ok is False
    assert checks["database_url"].ok is False
    assert checks["audit_anchor_tls"].ok is False



def test_production_configuration_rejects_static_identity_material(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "SERVICE_IDENTITIES_JSON",
        '{"legacy":{"token":"x","roles":["reader"]}}',
    )
    checks = {
        check.name: check
        for check in production_configuration_checks()
    }
    assert checks["static_identities_absent"].ok is False


def test_production_configuration_rejects_unbounded_abuse_limits(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "MAX_REQUEST_BODY_BYTES",
        "16777216",
    )
    monkeypatch.setenv(
        "BILLING_RATE_LIMIT_PER_MINUTE",
        "1000000",
    )
    checks = {
        check.name: check
        for check in production_configuration_checks()
    }
    assert checks["request_body_limit"].ok is False
    assert checks["billing_rate_limit"].ok is False
