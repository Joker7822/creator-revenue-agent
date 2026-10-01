import json
import os
from pathlib import Path

os.environ.setdefault(
    "CUSTOM_API_BASE_URL",
    "http://127.0.0.1:8000",
)
os.environ.setdefault(
    "CUSTOM_API_TOKEN",
    "test-token",
)
os.environ.setdefault(
    "INTERNAL_API_TOKEN",
    "test-token",
)
os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///./test-agent.db",
)
os.environ.setdefault(
    "ALLOW_LEGACY_ADMIN_TOKEN",
    "false",
)
os.environ.setdefault(
    "SERVICE_AUTH_MODE",
    "hybrid",
)
os.environ.setdefault(
    "SERVICE_JWT_KEYS_JSON",
    json.dumps(
        {
            "test-old": "old-signing-secret-0000000000000001",
            "test-new": "new-signing-secret-0000000000000002",
        }
    ),
)
os.environ.setdefault(
    "SERVICE_JWT_ACTIVE_KID",
    "test-old",
)
os.environ.setdefault(
    "SERVICE_JWT_ISSUER",
    "creator-revenue-agent-test",
)
os.environ.setdefault(
    "SERVICE_JWT_AUDIENCE",
    "creator-revenue-agent-test-internal",
)
os.environ.setdefault(
    "SERVICE_JWT_MAX_TTL_SECONDS",
    "900",
)
os.environ.setdefault(
    "SERVICE_JWT_REQUIRE_ISSUED_RECORD",
    "true",
)
os.environ.setdefault(
    "REQUIRE_TRUSTED_VERIFICATION",
    "false",
)
os.environ.setdefault(
    "VERIFICATION_WEBHOOK_KEYS_JSON",
    json.dumps(
        {
            "provider-a": {
                "old": (
                    "provider-old-secret-0000000000000000001"
                ),
                "new": (
                    "provider-new-secret-0000000000000000002"
                ),
            }
        }
    ),
)
os.environ.setdefault(
    "VERIFICATION_WEBHOOK_REQUIRE_KEY_ID",
    "true",
)
os.environ.setdefault(
    "VERIFICATION_WEBHOOK_MAX_AGE_SECONDS",
    "300",
)
os.environ.setdefault(
    "VERIFICATION_WEBHOOK_MAX_BODY_BYTES",
    "65536",
)
os.environ.setdefault(
    "AUDIT_HASH_KEYS_JSON",
    json.dumps(
        {
            "test-audit-2026-10": (
                "audit-hmac-secret-0000000000000000000001"
            )
        }
    ),
)
os.environ.setdefault(
    "AUDIT_HASH_ACTIVE_KID",
    "test-audit-2026-10",
)
os.environ.setdefault(
    "AUDIT_ANCHOR_BASE_URL",
    "https://audit-anchor.test",
)
os.environ.setdefault(
    "AUDIT_ANCHOR_TOKEN",
    "test-audit-anchor-service-token",
)
os.environ.setdefault(
    "AUDIT_ANCHOR_NAMESPACE",
    "creator-revenue-agent-test",
)
os.environ.setdefault(
    "AUDIT_ANCHOR_RECEIPT_KEYS_JSON",
    json.dumps(
        {
            "test-anchor-receipt-2026-10": (
                "anchor-receipt-secret-000000000000000001"
            )
        }
    ),
)
os.environ.setdefault(
    "AUDIT_ANCHOR_TIMEOUT_SECONDS",
    "5",
)
os.environ.setdefault(
    "SERVICE_IDENTITIES_JSON",
    json.dumps(
        {
            "test-admin": {
                "token": "test-token",
                "roles": ["admin"],
            },
            "credential-admin-service": {
                "token": "credential-admin-token",
                "roles": ["credential_admin"],
            },
            "verification-service": {
                "token": "verification-token",
                "roles": ["verification_writer"],
            },
            "audit-anchor-service": {
                "token": "audit-anchor-token",
                "roles": ["audit_anchor_operator"],
            },
            "reviewer-service": {
                "token": "reviewer-token",
                "roles": ["reviewer"],
            },
            "publisher-service": {
                "token": "publisher-token",
                "roles": ["publisher"],
            },
            "experiment-service": {
                "token": "experiment-token",
                "roles": ["experiment_operator"],
            },
            "planner-service": {
                "token": "planner-token",
                "roles": ["planner"],
            },
            "release-manager-service": {
                "token": "release-token",
                "roles": ["release_manager"],
            },
            "rollout-operator-service": {
                "token": "rollout-token",
                "roles": ["rollout_operator"],
            },
            "incident-manager-service": {
                "token": "incident-token",
                "roles": ["incident_manager"],
            },
            "read-only-service": {
                "token": "reader-token",
                "roles": ["reader"],
            },
        }
    ),
)

from alembic import command
from alembic.config import Config
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _reset_test_database() -> None:
    database_url = os.environ["DATABASE_URL"]
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        path = Path(database_url.removeprefix(prefix))
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            path.unlink()

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


_reset_test_database()

from api_server.db import Base, engine


@pytest.fixture(autouse=True)
def clean_database():
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())

    yield
