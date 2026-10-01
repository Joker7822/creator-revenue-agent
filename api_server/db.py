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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        index=True,
    )


def init_db() -> None:
    Base.metadata.create_all(engine)
