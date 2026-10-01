"""Add optimistic state versions for mutable workflows.

Revision ID: 20261001_0007
Revises: 20261001_0006
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_0007"
down_revision = "20261001_0006"
branch_labels = None
depends_on = None


TABLES = (
    "approvals",
    "products",
    "optimization_proposals",
    "experiments",
    "change_sets",
    "rollouts",
)


def _columns(table_name: str) -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_columns(
            table_name
        )
    }


def upgrade() -> None:
    for table_name in TABLES:
        if "state_version" in _columns(table_name):
            continue
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(
                sa.Column(
                    "state_version",
                    sa.Integer(),
                    nullable=False,
                    server_default=sa.text("1"),
                )
            )


def downgrade() -> None:
    for table_name in reversed(TABLES):
        if "state_version" not in _columns(table_name):
            continue
        with op.batch_alter_table(table_name) as batch:
            batch.drop_column("state_version")
