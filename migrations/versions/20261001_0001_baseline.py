"""Baseline schema and legacy create_all adoption.

Revision ID: 20261001_0001
Revises:
Create Date: 2026-10-01
"""

from collections.abc import Callable

from alembic import context, op
import sqlalchemy as sa


revision = "20261001_0001"
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    if context.is_offline_mode():
        return False
    return name in sa.inspect(op.get_bind()).get_table_names()


def _create_table(
    name: str,
    factory: Callable[[], None],
) -> None:
    if not _table_exists(name):
        factory()


def _ensure_index(
    table_name: str,
    index_name: str,
    columns: list[str],
) -> None:
    if context.is_offline_mode():
        op.create_index(
            index_name,
            table_name,
            columns,
            unique=False,
        )
        return

    inspector = sa.inspect(op.get_bind())
    existing = {
        row["name"]
        for row in inspector.get_indexes(table_name)
        if row.get("name")
    }
    if index_name not in existing:
        op.create_index(
            index_name,
            table_name,
            columns,
            unique=False,
        )


def upgrade() -> None:
    _create_table(
        "jobs",
        lambda: op.create_table(
            "jobs",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("campaign_type", sa.String(80), nullable=False),
            sa.Column("target_segment", sa.String(80), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("teaser", sa.Text(), nullable=False),
            sa.Column("price_cents", sa.Integer(), nullable=False),
            sa.Column("creator_age", sa.Integer(), nullable=True),
            sa.Column("age_verified", sa.Boolean(), nullable=False),
            sa.Column("consent_verified", sa.Boolean(), nullable=False),
            sa.Column("depicts_real_person", sa.Boolean(), nullable=False),
            sa.Column(
                "real_person_consent_verified",
                sa.Boolean(),
                nullable=False,
            ),
            sa.Column("policy_allowed", sa.Boolean(), nullable=True),
            sa.Column(
                "policy_reasons_json",
                sa.Text(),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
        ),
    )

    _create_table(
        "approvals",
        lambda: op.create_table(
            "approvals",
            sa.Column(
                "job_id",
                sa.String(128),
                sa.ForeignKey("jobs.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("required", sa.Boolean(), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "decided_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        ),
    )

    _create_table(
        "publications",
        lambda: op.create_table(
            "publications",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "job_id",
                sa.String(128),
                sa.ForeignKey("jobs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("destination", sa.String(120), nullable=False),
            sa.Column("publisher", sa.String(120), nullable=False),
            sa.Column(
                "published_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "job_id",
                name="uq_publications_job_id",
            ),
        ),
    )
    _ensure_index(
        "publications",
        "ix_publications_job_id",
        ["job_id"],
    )

    _create_table(
        "products",
        lambda: op.create_table(
            "products",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "publication_id",
                sa.String(128),
                sa.ForeignKey(
                    "publications.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column(
                "price_minor_units",
                sa.Integer(),
                nullable=False,
            ),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
        ),
    )
    _ensure_index(
        "products",
        "ix_products_publication_id",
        ["publication_id"],
    )
    _ensure_index(
        "products",
        "ix_products_currency",
        ["currency"],
    )

    _create_table(
        "transactions",
        lambda: op.create_table(
            "transactions",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "product_id",
                sa.String(128),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column(
                "amount_minor_units",
                sa.Integer(),
                nullable=False,
            ),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
        ),
    )
    for name, columns in (
        ("ix_transactions_product_id", ["product_id"]),
        ("ix_transactions_kind", ["kind"]),
        ("ix_transactions_currency", ["currency"]),
        ("ix_transactions_occurred_at", ["occurred_at"]),
    ):
        _ensure_index("transactions", name, columns)

    _create_table(
        "analytics_events",
        lambda: op.create_table(
            "analytics_events",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "publication_id",
                sa.String(128),
                sa.ForeignKey(
                    "publications.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=False),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
        ),
    )
    for name, columns in (
        (
            "ix_analytics_events_publication_id",
            ["publication_id"],
        ),
        ("ix_analytics_events_event_type", ["event_type"]),
        ("ix_analytics_events_occurred_at", ["occurred_at"]),
    ):
        _ensure_index("analytics_events", name, columns)

    _create_table(
        "optimization_proposals",
        lambda: op.create_table(
            "optimization_proposals",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "publication_id",
                sa.String(128),
                sa.ForeignKey(
                    "publications.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                sa.String(128),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("window", sa.String(16), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("metrics_json", sa.Text(), nullable=False),
            sa.Column(
                "recommendations_json",
                sa.Text(),
                nullable=False,
            ),
            sa.Column("reviewer", sa.String(120), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "decided_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        ),
    )
    for name, columns in (
        (
            "ix_optimization_proposals_publication_id",
            ["publication_id"],
        ),
        (
            "ix_optimization_proposals_product_id",
            ["product_id"],
        ),
        ("ix_optimization_proposals_status", ["status"]),
    ):
        _ensure_index(
            "optimization_proposals",
            name,
            columns,
        )

    _create_table(
        "experiments",
        lambda: op.create_table(
            "experiments",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "proposal_id",
                sa.String(128),
                sa.ForeignKey(
                    "optimization_proposals.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "publication_id",
                sa.String(128),
                sa.ForeignKey(
                    "publications.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                sa.String(128),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "recommendation_index",
                sa.Integer(),
                nullable=False,
            ),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("plan_json", sa.Text(), nullable=False),
            sa.Column("owner", sa.String(120), nullable=False),
            sa.Column("outcome_json", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "completed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "proposal_id",
                "recommendation_index",
                name="uq_experiment_proposal_recommendation",
            ),
        ),
    )
    for name, columns in (
        ("ix_experiments_proposal_id", ["proposal_id"]),
        ("ix_experiments_publication_id", ["publication_id"]),
        ("ix_experiments_product_id", ["product_id"]),
        ("ix_experiments_status", ["status"]),
    ):
        _ensure_index("experiments", name, columns)

    _create_table(
        "experiment_assignments",
        lambda: op.create_table(
            "experiment_assignments",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "experiment_id",
                sa.String(128),
                sa.ForeignKey(
                    "experiments.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "subject_hash",
                sa.String(64),
                nullable=False,
            ),
            sa.Column("arm", sa.String(16), nullable=False),
            sa.Column(
                "assigned_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "experiment_id",
                "subject_hash",
                name="uq_experiment_assignment_subject",
            ),
        ),
    )
    for name, columns in (
        (
            "ix_experiment_assignments_experiment_id",
            ["experiment_id"],
        ),
        (
            "ix_experiment_assignments_subject_hash",
            ["subject_hash"],
        ),
        ("ix_experiment_assignments_arm", ["arm"]),
    ):
        _ensure_index(
            "experiment_assignments",
            name,
            columns,
        )

    _create_table(
        "experiment_events",
        lambda: op.create_table(
            "experiment_events",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "experiment_id",
                sa.String(128),
                sa.ForeignKey(
                    "experiments.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "assignment_id",
                sa.String(128),
                sa.ForeignKey(
                    "experiment_assignments.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("arm", sa.String(16), nullable=False),
            sa.Column("event_type", sa.String(32), nullable=False),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "recorded_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
        ),
    )
    for name, columns in (
        (
            "ix_experiment_events_experiment_id",
            ["experiment_id"],
        ),
        (
            "ix_experiment_events_assignment_id",
            ["assignment_id"],
        ),
        ("ix_experiment_events_arm", ["arm"]),
        ("ix_experiment_events_event_type", ["event_type"]),
        ("ix_experiment_events_occurred_at", ["occurred_at"]),
    ):
        _ensure_index("experiment_events", name, columns)

    _create_table(
        "experiment_transaction_links",
        lambda: op.create_table(
            "experiment_transaction_links",
            sa.Column(
                "transaction_id",
                sa.String(128),
                sa.ForeignKey(
                    "transactions.id",
                    ondelete="CASCADE",
                ),
                primary_key=True,
            ),
            sa.Column(
                "experiment_id",
                sa.String(128),
                sa.ForeignKey(
                    "experiments.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "assignment_id",
                sa.String(128),
                sa.ForeignKey(
                    "experiment_assignments.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("arm", sa.String(16), nullable=False),
            sa.Column(
                "linked_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
        ),
    )
    for name, columns in (
        (
            "ix_experiment_transaction_links_experiment_id",
            ["experiment_id"],
        ),
        (
            "ix_experiment_transaction_links_assignment_id",
            ["assignment_id"],
        ),
        ("ix_experiment_transaction_links_arm", ["arm"]),
    ):
        _ensure_index(
            "experiment_transaction_links",
            name,
            columns,
        )

    _create_table(
        "experiment_result_reviews",
        lambda: op.create_table(
            "experiment_result_reviews",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "experiment_id",
                sa.String(128),
                sa.ForeignKey(
                    "experiments.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("decision", sa.String(32), nullable=False),
            sa.Column("reviewer", sa.String(120), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column(
                "statistics_json",
                sa.Text(),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "experiment_id",
                name="uq_experiment_result_review_experiment",
            ),
        ),
    )
    _ensure_index(
        "experiment_result_reviews",
        "ix_experiment_result_reviews_experiment_id",
        ["experiment_id"],
    )

    _create_table(
        "change_sets",
        lambda: op.create_table(
            "change_sets",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "review_id",
                sa.String(128),
                sa.ForeignKey(
                    "experiment_result_reviews.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "experiment_id",
                sa.String(128),
                sa.ForeignKey(
                    "experiments.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                sa.String(128),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("change_type", sa.String(32), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("expected_json", sa.Text(), nullable=False),
            sa.Column("proposed_json", sa.Text(), nullable=False),
            sa.Column("created_by", sa.String(120), nullable=False),
            sa.Column("approver", sa.String(120), nullable=True),
            sa.Column("approval_reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "decided_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "review_id",
                name="uq_change_set_review",
            ),
        ),
    )
    for name, columns in (
        ("ix_change_sets_review_id", ["review_id"]),
        ("ix_change_sets_experiment_id", ["experiment_id"]),
        ("ix_change_sets_product_id", ["product_id"]),
        ("ix_change_sets_status", ["status"]),
    ):
        _ensure_index("change_sets", name, columns)

    _create_table(
        "rollouts",
        lambda: op.create_table(
            "rollouts",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "change_set_id",
                sa.String(128),
                sa.ForeignKey(
                    "change_sets.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("actor", sa.String(120), nullable=False),
            sa.Column("before_json", sa.Text(), nullable=False),
            sa.Column("after_json", sa.Text(), nullable=False),
            sa.Column(
                "applied_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "change_set_id",
                name="uq_rollout_change_set",
            ),
        ),
    )
    _ensure_index(
        "rollouts",
        "ix_rollouts_change_set_id",
        ["change_set_id"],
    )
    _ensure_index(
        "rollouts",
        "ix_rollouts_status",
        ["status"],
    )

    _create_table(
        "rollbacks",
        lambda: op.create_table(
            "rollbacks",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column(
                "rollout_id",
                sa.String(128),
                sa.ForeignKey(
                    "rollouts.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("actor", sa.String(120), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("before_json", sa.Text(), nullable=False),
            sa.Column("after_json", sa.Text(), nullable=False),
            sa.Column(
                "rolled_back_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "rollout_id",
                name="uq_rollback_rollout",
            ),
        ),
    )
    _ensure_index(
        "rollbacks",
        "ix_rollbacks_rollout_id",
        ["rollout_id"],
    )

    _create_table(
        "issued_credentials",
        lambda: op.create_table(
            "issued_credentials",
            sa.Column("id", sa.String(128), primary_key=True),
            sa.Column("subject", sa.String(120), nullable=False),
            sa.Column("roles_json", sa.Text(), nullable=False),
            sa.Column("key_id", sa.String(120), nullable=False),
            sa.Column("issued_by", sa.String(120), nullable=False),
            sa.Column(
                "issued_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("revoked_by", sa.String(120), nullable=True),
            sa.Column("revoke_reason", sa.Text(), nullable=True),
        ),
    )
    for name, columns in (
        ("ix_issued_credentials_subject", ["subject"]),
        ("ix_issued_credentials_key_id", ["key_id"]),
        ("ix_issued_credentials_issued_at", ["issued_at"]),
        ("ix_issued_credentials_expires_at", ["expires_at"]),
        ("ix_issued_credentials_revoked_at", ["revoked_at"]),
    ):
        _ensure_index("issued_credentials", name, columns)

    _create_table(
        "audit_events",
        lambda: op.create_table(
            "audit_events",
            sa.Column(
                "id",
                sa.Integer(),
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column("job_id", sa.String(128), nullable=True),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("actor", sa.String(120), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
        ),
    )
    for name, columns in (
        ("ix_audit_events_job_id", ["job_id"]),
        ("ix_audit_events_event_type", ["event_type"]),
        ("ix_audit_events_created_at", ["created_at"]),
    ):
        _ensure_index("audit_events", name, columns)


def downgrade() -> None:
    for table_name in (
        "audit_events",
        "issued_credentials",
        "rollbacks",
        "rollouts",
        "change_sets",
        "experiment_result_reviews",
        "experiment_transaction_links",
        "experiment_events",
        "experiment_assignments",
        "experiments",
        "optimization_proposals",
        "analytics_events",
        "transactions",
        "products",
        "publications",
        "approvals",
        "jobs",
    ):
        if context.is_offline_mode() or _table_exists(table_name):
            op.drop_table(table_name)
