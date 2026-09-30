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
