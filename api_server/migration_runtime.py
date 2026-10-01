from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from api_server.db import engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def head_revision() -> str:
    script = ScriptDirectory.from_config(alembic_config())
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no head revision")
    return head


def current_revision() -> str | None:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def assert_database_current() -> None:
    current = current_revision()
    head = head_revision()
    if current != head:
        raise RuntimeError(
            "database schema is not current: "
            f"current={current!r}, head={head!r}; "
            "run 'alembic upgrade head'"
        )
