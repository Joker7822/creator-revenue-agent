from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from api_server.db import Base


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def config_for(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url",
        database_url.replace("%", "%%"),
    )
    return config


def revision_for(database_url: str) -> str | None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(
                connection
            ).get_current_revision()
    finally:
        engine.dispose()


def test_fresh_database_upgrades_to_head(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_for(database_url)

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    expected = set(Base.metadata.tables)
    assert expected.issubset(tables)
    assert "alembic_version" in tables

    head = ScriptDirectory.from_config(
        config
    ).get_current_head()
    assert revision_for(database_url) == head


def test_legacy_create_all_database_is_adopted(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    legacy_engine = create_engine(database_url)
    Base.metadata.create_all(legacy_engine)
    legacy_engine.dispose()

    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_for(database_url)
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert set(Base.metadata.tables).issubset(tables)
    assert "alembic_version" in tables
    head = ScriptDirectory.from_config(
        config
    ).get_current_head()
    assert revision_for(database_url) == head
