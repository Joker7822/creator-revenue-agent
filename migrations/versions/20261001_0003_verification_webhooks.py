"""Add verification webhook event ledger.

Revision ID: 20261001_0003
Revises: 20261001_0002
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_0003"
down_revision = "20261001_0002"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_indexes(table_name)
        if row.get("name")
    }


def upgrade() -> None:
    if "verification_webhook_events" not in _tables():
        op.create_table(
        "verification_webhook_events",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("provider", sa.String(120), nullable=False),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column(
            "verification_id",
            sa.String(128),
            sa.ForeignKey(
                "verification_records.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
            sa.UniqueConstraint(
                "provider",
                "event_id",
                name="uq_verification_webhook_provider_event",
            ),
        )

    existing = _indexes("verification_webhook_events")
    for name, columns in (
        (
            "ix_verification_webhook_events_provider",
            ["provider"],
        ),
        (
            "ix_verification_webhook_events_event_type",
            ["event_type"],
        ),
        (
            "ix_verification_webhook_events_verification_id",
            ["verification_id"],
        ),
        (
            "ix_verification_webhook_events_received_at",
            ["received_at"],
        ),
    ):
        if name not in existing:
            op.create_index(
                name,
                "verification_webhook_events",
                columns,
                unique=False,
            )


def downgrade() -> None:
    if "verification_webhook_events" in _tables():
        op.drop_table("verification_webhook_events")
