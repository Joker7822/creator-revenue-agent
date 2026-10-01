"""Link refunds to original sales.

Revision ID: 20261001_0008
Revises: 20261001_0007
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_0008"
down_revision = "20261001_0007"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    if "original_sale_id" not in _columns("transactions"):
        with op.batch_alter_table("transactions") as batch:
            batch.add_column(
                sa.Column(
                    "original_sale_id",
                    sa.String(length=128),
                    nullable=True,
                )
            )
            batch.create_foreign_key(
                "fk_transactions_original_sale_id",
                "transactions",
                ["original_sale_id"],
                ["id"],
                ondelete="RESTRICT",
            )

    if (
        "ix_transactions_original_sale_id"
        not in _indexes("transactions")
    ):
        op.create_index(
            "ix_transactions_original_sale_id",
            "transactions",
            ["original_sale_id"],
            unique=False,
        )


def downgrade() -> None:
    if (
        "ix_transactions_original_sale_id"
        in _indexes("transactions")
    ):
        op.drop_index(
            "ix_transactions_original_sale_id",
            table_name="transactions",
        )

    if "original_sale_id" in _columns("transactions"):
        with op.batch_alter_table("transactions") as batch:
            batch.drop_constraint(
                "fk_transactions_original_sale_id",
                type_="foreignkey",
            )
            batch.drop_column("original_sale_id")
