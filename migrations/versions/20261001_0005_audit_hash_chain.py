"""Add tamper-evident audit HMAC chain.

Revision ID: 20261001_0005
Revises: 20261001_0004
Create Date: 2026-10-01
"""

import hashlib
import json
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20261001_0005"
down_revision = "20261001_0004"
branch_labels = None
depends_on = None

ROOT_HASH = "0" * 64
LEGACY_KEY_ID = "legacy-sha256-v1"
EVENT_VERSION = "audit-event-v1"
HEAD_VERSION = "audit-head-v1"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_columns(
            table_name
        )
    }


def _indexes(table_name: str) -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_indexes(
            table_name
        )
        if row.get("name")
    }


def _timestamp(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    value = value.replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


def _sha(data: dict) -> str:
    canonical = json.dumps(
        data,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _event_hash(
    *,
    event_id: int,
    job_id: str | None,
    event_type: str,
    actor: str | None,
    payload_json: str,
    created_at: datetime | str,
    previous_hash: str,
) -> str:
    return _sha(
        {
            "actor": actor,
            "created_at": _timestamp(created_at),
            "event_type": event_type,
            "hash_key_id": LEGACY_KEY_ID,
            "id": event_id,
            "job_id": job_id,
            "payload_json": payload_json,
            "previous_hash": previous_hash,
            "version": EVENT_VERSION,
        }
    )


def _head_hash(
    *,
    last_event_id: int | None,
    last_hash: str,
) -> str:
    return _sha(
        {
            "hash_key_id": LEGACY_KEY_ID,
            "last_event_id": last_event_id,
            "last_hash": last_hash,
            "version": HEAD_VERSION,
        }
    )


def upgrade() -> None:
    existing = _columns("audit_events")
    with op.batch_alter_table("audit_events") as batch:
        if "previous_hash" not in existing:
            batch.add_column(
                sa.Column(
                    "previous_hash",
                    sa.String(64),
                    nullable=True,
                )
            )
        if "hash_key_id" not in existing:
            batch.add_column(
                sa.Column(
                    "hash_key_id",
                    sa.String(120),
                    nullable=True,
                )
            )
        if "event_hash" not in existing:
            batch.add_column(
                sa.Column(
                    "event_hash",
                    sa.String(64),
                    nullable=True,
                )
            )

    bind = op.get_bind()
    metadata = sa.MetaData()
    audit = sa.Table(
        "audit_events",
        metadata,
        autoload_with=bind,
    )
    rows = bind.execute(
        sa.select(audit).order_by(audit.c.id.asc())
    ).mappings().all()

    previous_hash = ROOT_HASH
    last_event_id = None
    for row in rows:
        event_hash = _event_hash(
            event_id=row["id"],
            job_id=row["job_id"],
            event_type=row["event_type"],
            actor=row["actor"],
            payload_json=row["payload_json"] or "{}",
            created_at=row["created_at"],
            previous_hash=previous_hash,
        )
        bind.execute(
            audit.update()
            .where(audit.c.id == row["id"])
            .values(
                previous_hash=previous_hash,
                hash_key_id=LEGACY_KEY_ID,
                event_hash=event_hash,
            )
        )
        previous_hash = event_hash
        last_event_id = row["id"]

    with op.batch_alter_table("audit_events") as batch:
        batch.alter_column(
            "previous_hash",
            existing_type=sa.String(64),
            nullable=False,
        )
        batch.alter_column(
            "hash_key_id",
            existing_type=sa.String(120),
            nullable=False,
        )
        batch.alter_column(
            "event_hash",
            existing_type=sa.String(64),
            nullable=False,
        )

    existing_indexes = _indexes("audit_events")
    for name, columns in (
        ("ix_audit_events_hash_key_id", ["hash_key_id"]),
        ("ix_audit_events_event_hash", ["event_hash"]),
    ):
        if name not in existing_indexes:
            op.create_index(
                name,
                "audit_events",
                columns,
                unique=False,
            )

    if "audit_chain_state" not in _tables():
        op.create_table(
            "audit_chain_state",
            sa.Column(
                "id",
                sa.Integer(),
                primary_key=True,
            ),
            sa.Column(
                "last_event_id",
                sa.Integer(),
                nullable=True,
            ),
            sa.Column(
                "last_hash",
                sa.String(64),
                nullable=False,
            ),
            sa.Column(
                "hash_key_id",
                sa.String(120),
                nullable=False,
            ),
            sa.Column(
                "state_hash",
                sa.String(64),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
        )

    state = sa.Table(
        "audit_chain_state",
        sa.MetaData(),
        autoload_with=bind,
    )
    bind.execute(
        state.delete().where(state.c.id == 1)
    )
    bind.execute(
        state.insert().values(
            id=1,
            last_event_id=last_event_id,
            last_hash=previous_hash,
            hash_key_id=LEGACY_KEY_ID,
            state_hash=_head_hash(
                last_event_id=last_event_id,
                last_hash=previous_hash,
            ),
            updated_at=datetime.now(timezone.utc),
        )
    )


def downgrade() -> None:
    if "audit_chain_state" in _tables():
        op.drop_table("audit_chain_state")

    for name in (
        "ix_audit_events_event_hash",
        "ix_audit_events_hash_key_id",
    ):
        if name in _indexes("audit_events"):
            op.drop_index(
                name,
                table_name="audit_events",
            )

    existing = _columns("audit_events")
    with op.batch_alter_table("audit_events") as batch:
        if "event_hash" in existing:
            batch.drop_column("event_hash")
        if "hash_key_id" in existing:
            batch.drop_column("hash_key_id")
        if "previous_hash" in existing:
            batch.drop_column("previous_hash")
