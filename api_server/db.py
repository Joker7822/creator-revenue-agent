from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agent.db")
_connect_args = (
    {"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    campaign_type: Mapped[str] = mapped_column(String(80))
    target_segment: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    teaser: Mapped[str] = mapped_column(Text)
    price_cents: Mapped[int] = mapped_column(Integer)

    creator_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    depicts_real_person: Mapped[bool] = mapped_column(Boolean, default=False)
    real_person_consent_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )
    creator_ref: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )
    age_verification_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("verification_records.id"),
        nullable=True,
        index=True,
    )
    consent_verification_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("verification_records.id"),
        nullable=True,
        index=True,
    )
    real_person_consent_verification_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("verification_records.id"),
        nullable=True,
        index=True,
    )

    policy_allowed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    policy_reasons_json: Mapped[str] = mapped_column(Text, default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class VerificationRecord(Base):
    __tablename__ = "verification_records"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject_ref: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="active",
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    source_record_ref: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )
    age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    revoked_by: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class VerificationWebhookEventRecord(Base):
    __tablename__ = "verification_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "event_id",
            name="uq_verification_webhook_provider_event",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )
    key_id: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )
    event_id: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        index=True,
    )
    body_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    verification_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("verification_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    job_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="pending_review")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    reviewer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class PublicationRecord(Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_publications_job_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), default="published")
    destination: Mapped[str] = mapped_column(String(120), default="internal")
    publisher: Mapped[str] = mapped_column(String(120), default="agent")
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class ProductRecord(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3), index=True)
    price_minor_units: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class TransactionRecord(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), index=True)
    amount_minor_units: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class AnalyticsEventRecord(Base):
    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class OptimizationProposalRecord(Base):
    __tablename__ = "optimization_proposals"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    publication_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    window: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending_review",
        index=True,
    )
    metrics_json: Mapped[str] = mapped_column(Text)
    recommendations_json: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ExperimentRecord(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id",
            "recommendation_index",
            name="uq_experiment_proposal_recommendation",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("optimization_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    publication_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("publications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recommendation_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(32),
        default="draft",
        index=True,
    )
    plan_json: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(120))
    outcome_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ExperimentAssignmentRecord(Base):
    __tablename__ = "experiment_assignments"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "subject_hash",
            name="uq_experiment_assignment_subject",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    arm: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class ExperimentEventRecord(Base):
    __tablename__ = "experiment_events"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("experiment_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    arm: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class ExperimentTransactionLinkRecord(Base):
    __tablename__ = "experiment_transaction_links"

    transaction_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("transactions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    experiment_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("experiment_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    arm: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class ExperimentResultReviewRecord(Base):
    __tablename__ = "experiment_result_reviews"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            name="uq_experiment_result_review_experiment",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    statistics_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class ChangeSetRecord(Base):
    __tablename__ = "change_sets"
    __table_args__ = (
        UniqueConstraint(
            "review_id",
            name="uq_change_set_review",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("experiment_result_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    experiment_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("experiments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="pending_approval",
        index=True,
    )
    expected_json: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    approver: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class RolloutRecord(Base):
    __tablename__ = "rollouts"
    __table_args__ = (
        UniqueConstraint(
            "change_set_id",
            name="uq_rollout_change_set",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    change_set_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("change_sets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default="applied",
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class RollbackRecord(Base):
    __tablename__ = "rollbacks"
    __table_args__ = (
        UniqueConstraint(
            "rollout_id",
            name="uq_rollback_rollout",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    rollout_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("rollouts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    before_json: Mapped[str] = mapped_column(Text, nullable=False)
    after_json: Mapped[str] = mapped_column(Text, nullable=False)
    rolled_back_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
    )


class IssuedCredentialRecord(Base):
    __tablename__ = "issued_credentials"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )
    roles_json: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )
    issued_by: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    revoked_by: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )
    revoke_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )


class AuditChainState(Base):
    __tablename__ = "audit_chain_state"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    last_event_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    last_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    hash_key_id: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    state_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    job_id: Mapped[str | None] = mapped_column(
        String(128),
        index=True,
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    previous_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    hash_key_id: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
    )
    event_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )

