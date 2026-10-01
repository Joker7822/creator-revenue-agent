import json
import os

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

import pytest

from api_server.db import Base, engine, init_db


@pytest.fixture(autouse=True)
def clean_database():
    init_db()

    with engine.begin() as conn:
        for table in reversed(
            Base.metadata.sorted_tables
        ):
            conn.execute(table.delete())

    yield
