"""Add webhook signing key id.

Revision ID: 20261001_0004
Revises: 20261001_0003
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_0004"
down_revision = "20261001_0003"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_columns(
            "verification_webhook_events"
        )
    }


def _indexes() -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_indexes(
            "verification_webhook_events"
        )
        if row.get("name")
    }


def upgrade() -> None:
    if "key_id" not in _columns():
        with op.batch_alter_table(
            "verification_webhook_events"
        ) as batch:
            batch.add_column(
                sa.Column(
                    "key_id",
                    sa.String(120),
                    nullable=True,
                )
            )

        op.execute(
            sa.text(
                "UPDATE verification_webhook_events "
                "SET key_id = 'legacy' "
                "WHERE key_id IS NULL"
            )
        )

        with op.batch_alter_table(
            "verification_webhook_events"
        ) as batch:
            batch.alter_column(
                "key_id",
                existing_type=sa.String(120),
                nullable=False,
            )

    if (
        "ix_verification_webhook_events_key_id"
        not in _indexes()
    ):
        op.create_index(
            "ix_verification_webhook_events_key_id",
            "verification_webhook_events",
            ["key_id"],
            unique=False,
        )


def downgrade() -> None:
    if (
        "ix_verification_webhook_events_key_id"
        in _indexes()
    ):
        op.drop_index(
            "ix_verification_webhook_events_key_id",
            table_name="verification_webhook_events",
        )

    if "key_id" in _columns():
        with op.batch_alter_table(
            "verification_webhook_events"
        ) as batch:
            batch.drop_column("key_id")
