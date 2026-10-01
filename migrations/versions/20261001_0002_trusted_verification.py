"""Add trusted verification registry.

Revision ID: 20261001_0002
Revises: 20261001_0001
Create Date: 2026-10-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20261001_0002"
down_revision = "20261001_0001"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table_name: str) -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _indexes(table_name: str) -> set[str]:
    return {
        row["name"]
        for row in sa.inspect(op.get_bind()).get_indexes(table_name)
        if row.get("name")
    }


def upgrade() -> None:
    if "verification_records" not in _tables():
        op.create_table(
            "verification_records",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("subject_ref", sa.String(128), nullable=False),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("status", sa.String(24), nullable=False),
            sa.Column("source", sa.String(120), nullable=False),
            sa.Column("source_record_ref", sa.String(200), nullable=True),
            sa.Column("age_years", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.String(120), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("revoked_by", sa.String(120), nullable=True),
            sa.Column("revoke_reason", sa.Text(), nullable=True),
        )

    existing_indexes = _indexes("verification_records")
    for name, columns in (
        ("ix_verification_records_subject_ref", ["subject_ref"]),
        ("ix_verification_records_kind", ["kind"]),
        ("ix_verification_records_status", ["status"]),
        ("ix_verification_records_expires_at", ["expires_at"]),
        ("ix_verification_records_revoked_at", ["revoked_at"]),
    ):
        if name not in existing_indexes:
            op.create_index(
                name,
                "verification_records",
                columns,
                unique=False,
            )

    existing = _columns("jobs")
    additions = (
        (
            "creator_ref",
            sa.Column("creator_ref", sa.String(128), nullable=True),
        ),
        (
            "age_verification_id",
            sa.Column(
                "age_verification_id",
                sa.String(128),
                nullable=True,
            ),
        ),
        (
            "consent_verification_id",
            sa.Column(
                "consent_verification_id",
                sa.String(128),
                nullable=True,
            ),
        ),
        (
            "real_person_consent_verification_id",
            sa.Column(
                "real_person_consent_verification_id",
                sa.String(128),
                nullable=True,
            ),
        ),
    )
    with op.batch_alter_table("jobs") as batch:
        for name, column in additions:
            if name not in existing:
                batch.add_column(column)

    existing_indexes = _indexes("jobs")
    for name, columns in (
        ("ix_jobs_creator_ref", ["creator_ref"]),
        ("ix_jobs_age_verification_id", ["age_verification_id"]),
        (
            "ix_jobs_consent_verification_id",
            ["consent_verification_id"],
        ),
        (
            "ix_jobs_real_person_consent_verification_id",
            ["real_person_consent_verification_id"],
        ),
    ):
        if name not in existing_indexes:
            op.create_index(name, "jobs", columns, unique=False)


def downgrade() -> None:
    for name in (
        "ix_jobs_real_person_consent_verification_id",
        "ix_jobs_consent_verification_id",
        "ix_jobs_age_verification_id",
        "ix_jobs_creator_ref",
    ):
        if name in _indexes("jobs"):
            op.drop_index(name, table_name="jobs")

    existing = _columns("jobs")
    with op.batch_alter_table("jobs") as batch:
        for name in (
            "real_person_consent_verification_id",
            "consent_verification_id",
            "age_verification_id",
            "creator_ref",
        ):
            if name in existing:
                batch.drop_column(name)

    if "verification_records" in _tables():
        op.drop_table("verification_records")
