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



def test_audit_chain_backfills_from_0004(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = (
        f"sqlite:///{tmp_path / 'audit-0004.db'}"
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_for(database_url)

    command.upgrade(config, "20261001_0004")

    engine = create_engine(database_url)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO audit_events (
                        job_id,
                        event_type,
                        actor,
                        payload_json,
                        created_at
                    ) VALUES (
                        :job_id,
                        :event_type,
                        :actor,
                        :payload_json,
                        :created_at
                    )
                    """
                ),
                {
                    "job_id": "job_migration",
                    "event_type": "job_created",
                    "actor": "system",
                    "payload_json": "{}",
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO audit_events (
                        job_id,
                        event_type,
                        actor,
                        payload_json,
                        created_at
                    ) VALUES (
                        :job_id,
                        :event_type,
                        :actor,
                        :payload_json,
                        :created_at
                    )
                    """
                ),
                {
                    "job_id": "job_migration",
                    "event_type": "policy_evaluated",
                    "actor": "system",
                    "payload_json": (
                        '{"allowed":true,"reasons":[]}'
                    ),
                    "created_at": now,
                },
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        id,
                        previous_hash,
                        hash_key_id,
                        event_hash
                    FROM audit_events
                    ORDER BY id
                    """
                )
            ).mappings().all()
            state = connection.execute(
                text(
                    """
                    SELECT
                        last_event_id,
                        last_hash,
                        hash_key_id,
                        state_hash
                    FROM audit_chain_state
                    WHERE id = 1
                    """
                )
            ).mappings().one()
    finally:
        engine.dispose()

    assert len(rows) == 2
    assert rows[0]["previous_hash"] == "0" * 64
    assert rows[0]["hash_key_id"] == "legacy-sha256-v1"
    assert rows[1]["previous_hash"] == rows[0]["event_hash"]
    assert rows[1]["hash_key_id"] == "legacy-sha256-v1"
    assert state["last_event_id"] == rows[1]["id"]
    assert state["last_hash"] == rows[1]["event_hash"]
    assert state["hash_key_id"] == "legacy-sha256-v1"
    assert len(state["state_hash"]) == 64



def test_state_versions_upgrade_from_0006(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = (
        f"sqlite:///{tmp_path / 'state-version-0006.db'}"
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_for(database_url)

    command.upgrade(config, "20261001_0006")

    engine = create_engine(database_url)
    now = datetime.now(timezone.utc)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO approvals (
                        job_id,
                        status,
                        required,
                        created_at
                    ) VALUES (
                        'job_version_test',
                        'pending_review',
                        1,
                        :created_at
                    )
                    """
                ),
                {"created_at": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO products (
                        id,
                        publication_id,
                        name,
                        currency,
                        price_minor_units,
                        active,
                        created_at
                    ) VALUES (
                        'prod_version_test',
                        'pub_version_test',
                        'Version test',
                        'JPY',
                        1500,
                        1,
                        :created_at
                    )
                    """
                ),
                {"created_at": now},
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        for table_name in (
            "approvals",
            "products",
            "optimization_proposals",
            "experiments",
            "change_sets",
            "rollouts",
        ):
            columns = {
                column["name"]: column
                for column in inspector.get_columns(table_name)
            }
            assert "state_version" in columns
            assert columns["state_version"]["nullable"] is False

        with engine.connect() as connection:
            approval_version = connection.execute(
                text(
                    """
                    SELECT state_version
                    FROM approvals
                    WHERE job_id = 'job_version_test'
                    """
                )
            ).scalar_one()
            product_version = connection.execute(
                text(
                    """
                    SELECT state_version
                    FROM products
                    WHERE id = 'prod_version_test'
                    """
                )
            ).scalar_one()
    finally:
        engine.dispose()

    assert approval_version == 1
    assert product_version == 1



def test_refund_link_upgrade_from_0007(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = (
        f"sqlite:///{tmp_path / 'refund-link-0007.db'}"
    )
    monkeypatch.setenv("DATABASE_URL", database_url)
    config = config_for(database_url)

    command.upgrade(config, "20261001_0007")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("transactions")
        }
        indexes = {
            index["name"]
            for index in inspector.get_indexes("transactions")
        }
        foreign_keys = inspector.get_foreign_keys("transactions")
    finally:
        engine.dispose()

    assert "original_sale_id" in columns
    assert columns["original_sale_id"]["nullable"] is True
    assert "ix_transactions_original_sale_id" in indexes
    assert any(
        fk["referred_table"] == "transactions"
        and fk["constrained_columns"] == ["original_sale_id"]
        for fk in foreign_keys
    )
