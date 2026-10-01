"""Add external audit anchor receipt records.

Revision ID: 20261001_0006
Revises: 20261001_0005
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_0006"
down_revision = "20261001_0005"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table_name: str) -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_indexes(
            table_name
        )
        if row.get("name")
    }


def upgrade() -> None:
    if "audit_anchor_receipts" not in _tables():
        op.create_table(
            "audit_anchor_receipts",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "anchor_id",
                sa.String(128),
                nullable=False,
            ),
            sa.Column(
                "namespace",
                sa.String(120),
                nullable=False,
            ),
            sa.Column(
                "head_event_id",
                sa.Integer(),
                nullable=True,
            ),
            sa.Column(
                "head_hash",
                sa.String(64),
                nullable=False,
            ),
            sa.Column(
                "head_state_hash",
                sa.String(64),
                nullable=False,
            ),
            sa.Column(
                "head_hash_key_id",
                sa.String(120),
                nullable=False,
            ),
            sa.Column(
                "requested_by",
                sa.String(120),
                nullable=False,
            ),
            sa.Column(
                "remote_receipt_id",
                sa.String(200),
                nullable=False,
            ),
            sa.Column(
                "remote_receipt_key_id",
                sa.String(120),
                nullable=False,
            ),
            sa.Column(
                "remote_receipt_signature",
                sa.String(64),
                nullable=False,
            ),
            sa.Column(
                "anchored_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "anchor_id",
                name="uq_audit_anchor_receipts_anchor_id",
            ),
        )

    existing = _indexes("audit_anchor_receipts")
    for name, columns in (
        (
            "ix_audit_anchor_receipts_namespace",
            ["namespace"],
        ),
        (
            "ix_audit_anchor_receipts_head_event_id",
            ["head_event_id"],
        ),
        (
            "ix_audit_anchor_receipts_anchored_at",
            ["anchored_at"],
        ),
    ):
        if name not in existing:
            op.create_index(
                name,
                "audit_anchor_receipts",
                columns,
                unique=False,
            )


def downgrade() -> None:
    if "audit_anchor_receipts" in _tables():
        op.drop_table("audit_anchor_receipts")
