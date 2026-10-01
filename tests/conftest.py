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
    "SERVICE_IDENTITIES_JSON",
    json.dumps(
        {
            "test-admin": {
                "token": "test-token",
                "roles": ["admin"],
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
