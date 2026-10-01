from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

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



def test_webhook_key_id_backfills_from_0003(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = (
        f"sqlite:///{tmp_path / 'webhook-0003.db'}"
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_for(database_url)

    command.upgrade(config, "20261001_0003")

    engine = create_engine(database_url)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO verification_records (
                        id,
                        subject_ref,
                        kind,
                        status,
                        source,
                        source_record_ref,
                        age_years,
                        created_by,
                        created_at,
                        expires_at,
                        revoked_at,
                        revoked_by,
                        revoke_reason
                    ) VALUES (
                        :id,
                        :subject_ref,
                        :kind,
                        :status,
                        :source,
                        :source_record_ref,
                        :age_years,
                        :created_by,
                        :created_at,
                        NULL,
                        NULL,
                        NULL,
                        NULL
                    )
                    """
                ),
                {
                    "id": "ver_migration_test",
                    "subject_ref": "creator-migration",
                    "kind": "age",
                    "status": "active",
                    "source": "provider-a",
                    "source_record_ref": "external-migration",
                    "age_years": 21,
                    "created_by": "webhook:provider-a",
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO verification_webhook_events (
                        id,
                        provider,
                        event_id,
                        event_type,
                        body_sha256,
                        verification_id,
                        result_json,
                        received_at
                    ) VALUES (
                        :id,
                        :provider,
                        :event_id,
                        :event_type,
                        :body_sha256,
                        :verification_id,
                        :result_json,
                        :received_at
                    )
                    """
                ),
                {
                    "id": "vwh_migration_test",
                    "provider": "provider-a",
                    "event_id": "evt-migration-test",
                    "event_type": "verification.verified",
                    "body_sha256": "0" * 64,
                    "verification_id": "ver_migration_test",
                    "result_json": "{}",
                    "received_at": now,
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            key_id = connection.execute(
                text(
                    """
                    SELECT key_id
                    FROM verification_webhook_events
                    WHERE id = 'vwh_migration_test'
                    """
                )
            ).scalar_one()
    finally:
        engine.dispose()

    assert key_id == "legacy"
