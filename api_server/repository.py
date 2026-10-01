from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.db import (
    ApprovalRecord,
    AuditEvent,
    JobRecord,
    ProductRecord,
    PublicationRecord,
    TransactionRecord,
)
from api_server.schemas import (
    ApprovalResponse,
    AuditEventResponse,
    ContentGenerateRequest,
    ContentGenerateResponse,
    ProductResponse,
    PublicationResponse,
    RevenueCurrencySummary,
    RevenueResponse,
    TransactionResponse,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def add_audit(
    session: Session,
    *,
    job_id: str | None,
    event_type: str,
    actor: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        job_id=job_id,
        event_type=event_type,
        actor=actor,
        payload_json=json.dumps(
            payload or {},
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    session.add(event)
    return event


def create_job(
    session: Session,
    request: ContentGenerateRequest,
    response: ContentGenerateResponse,
) -> JobRecord:
    job = JobRecord(
        id=response.job_id,
        campaign_type=request.campaign_type,
        target_segment=request.target_segment,
        title=response.title,
        teaser=response.teaser,
        price_cents=response.price_cents,
        creator_age=response.creator_age,
        age_verified=response.age_verified,
        consent_verified=response.consent_verified,
        depicts_real_person=response.depicts_real_person,
        real_person_consent_verified=response.real_person_consent_verified,
    )
    session.add(job)
    add_audit(
        session,
        job_id=job.id,
        event_type="job_created",
        actor="system",
    )
    session.commit()
    session.refresh(job)
    return job


def set_policy_result(
    session: Session,
    *,
    job_id: str,
    allowed: bool,
    reasons: list[str],
) -> JobRecord:
    job = session.get(JobRecord, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )

    job.policy_allowed = allowed
    job.policy_reasons_json = json.dumps(reasons, separators=(",", ":"))
    add_audit(
        session,
        job_id=job_id,
        event_type="policy_evaluated",
        actor="system",
        payload={"allowed": allowed, "reasons": reasons},
    )
    session.commit()
    session.refresh(job)
    return job


def _approval_response(record: ApprovalRecord) -> ApprovalResponse:
    return ApprovalResponse(
        job_id=record.job_id,
        status=record.status,
        required=record.required,
        reviewer=record.reviewer,
        reason=record.reason,
        created_at=record.created_at,
        decided_at=record.decided_at,
    )


def create_approval(
    session: Session,
    *,
    job_id: str,
    required: bool,
) -> ApprovalResponse:
    job = session.get(JobRecord, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.policy_allowed is not True:
        raise HTTPException(status_code=409, detail="policy approval required")

    existing = session.get(ApprovalRecord, job_id)
    if existing is not None:
        return _approval_response(existing)

    now = utcnow()
    approval = ApprovalRecord(
        job_id=job_id,
        required=required,
        status="pending_review" if required else "approved",
        reviewer=None if required else "system",
        decided_at=None if required else now,
    )
    session.add(approval)
    add_audit(
        session,
        job_id=job_id,
        event_type="approval_created",
        actor="system",
        payload={"required": required, "status": approval.status},
    )
    if not required:
        add_audit(
            session,
            job_id=job_id,
            event_type="approval_approved",
            actor="system",
            payload={"reason": "human_review_not_required"},
        )
    session.commit()
    session.refresh(approval)
    return _approval_response(approval)


def get_approval(session: Session, job_id: str) -> ApprovalResponse:
    approval = session.get(ApprovalRecord, job_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return _approval_response(approval)


def decide_approval(
    session: Session,
    *,
    job_id: str,
    decision: str,
    reviewer: str,
    reason: str | None,
) -> ApprovalResponse:
    approval = session.get(ApprovalRecord, job_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")

    if approval.status != "pending_review":
        if approval.status == decision:
            return _approval_response(approval)
        raise HTTPException(
            status_code=409,
            detail=f"approval already {approval.status}",
        )

    approval.status = decision
    approval.reviewer = reviewer
    approval.reason = reason
    approval.decided_at = utcnow()
    add_audit(
        session,
        job_id=job_id,
        event_type=f"approval_{decision}",
        actor=reviewer,
        payload={"reason": reason} if reason else {},
    )
    session.commit()
    session.refresh(approval)
    return _approval_response(approval)


def _publication_response(record: PublicationRecord) -> PublicationResponse:
    return PublicationResponse(
        publication_id=record.id,
        job_id=record.job_id,
        status=record.status,
        destination=record.destination,
        publisher=record.publisher,
        published_at=record.published_at,
    )


def publish_job(
    session: Session,
    *,
    job_id: str,
    destination: str,
    publisher: str,
) -> PublicationResponse:
    job = session.get(JobRecord, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.policy_allowed is not True:
        raise HTTPException(status_code=409, detail="policy approval required")

    approval = session.get(ApprovalRecord, job_id)
    if approval is None or approval.status != "approved":
        raise HTTPException(status_code=409, detail="human approval required")

    existing = session.scalar(
        select(PublicationRecord).where(PublicationRecord.job_id == job_id)
    )
    if existing is not None:
        return _publication_response(existing)

    publication = PublicationRecord(
        id=f"pub_{uuid4().hex}",
        job_id=job_id,
        status="published",
        destination=destination,
        publisher=publisher,
    )
    session.add(publication)
    add_audit(
        session,
        job_id=job_id,
        event_type="publication_published",
        actor=publisher,
        payload={
            "publication_id": publication.id,
            "destination": destination,
        },
    )
    session.commit()
    session.refresh(publication)
    return _publication_response(publication)


def get_publication(session: Session, job_id: str) -> PublicationResponse:
    record = session.scalar(
        select(PublicationRecord).where(PublicationRecord.job_id == job_id)
    )
    if record is None:
        raise HTTPException(status_code=404, detail="publication not found")
    return _publication_response(record)


def _product_response(record: ProductRecord) -> ProductResponse:
    return ProductResponse(
        product_id=record.id,
        publication_id=record.publication_id,
        name=record.name,
        currency=record.currency,
        price_minor_units=record.price_minor_units,
        active=record.active,
        created_at=record.created_at,
    )


def create_product(
    session: Session,
    *,
    publication_id: str,
    name: str,
    currency: str,
    price_minor_units: int,
) -> ProductResponse:
    publication = session.get(PublicationRecord, publication_id)
    if publication is None or publication.status != "published":
        raise HTTPException(
            status_code=409,
            detail="published publication required",
        )

    product = ProductRecord(
        id=f"prod_{uuid4().hex}",
        publication_id=publication_id,
        name=name,
        currency=currency,
        price_minor_units=price_minor_units,
        active=True,
    )
    session.add(product)
    add_audit(
        session,
        job_id=publication.job_id,
        event_type="product_created",
        actor="billing",
        payload={
            "product_id": product.id,
            "currency": currency,
            "price_minor_units": price_minor_units,
        },
    )
    session.commit()
    session.refresh(product)
    return _product_response(product)


def get_product(session: Session, product_id: str) -> ProductResponse:
    product = session.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    return _product_response(product)


def _transaction_response(record: TransactionRecord) -> TransactionResponse:
    return TransactionResponse(
        transaction_id=record.id,
        product_id=record.product_id,
        kind=record.kind,
        amount_minor_units=record.amount_minor_units,
        currency=record.currency,
        occurred_at=record.occurred_at,
        recorded_at=record.recorded_at,
    )


def record_transaction(
    session: Session,
    *,
    transaction_id: str,
    product_id: str,
    kind: str,
    amount_minor_units: int,
    currency: str,
    occurred_at: datetime | None,
) -> TransactionResponse:
    product = session.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    if not product.active:
        raise HTTPException(status_code=409, detail="product inactive")
    if product.currency != currency:
        raise HTTPException(status_code=409, detail="currency mismatch")

    existing = session.get(TransactionRecord, transaction_id)
    if existing is not None:
        same = (
            existing.product_id == product_id
            and existing.kind == kind
            and existing.amount_minor_units == amount_minor_units
            and existing.currency == currency
        )
        if not same:
            raise HTTPException(
                status_code=409,
                detail="transaction idempotency conflict",
            )
        return _transaction_response(existing)

    publication = session.get(PublicationRecord, product.publication_id)
    transaction = TransactionRecord(
        id=transaction_id,
        product_id=product_id,
        kind=kind,
        amount_minor_units=amount_minor_units,
        currency=currency,
        occurred_at=occurred_at or utcnow(),
    )
    session.add(transaction)
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="transaction_recorded",
        actor="billing",
        payload={
            "transaction_id": transaction_id,
            "product_id": product_id,
            "kind": kind,
            "amount_minor_units": amount_minor_units,
            "currency": currency,
        },
    )
    session.commit()
    session.refresh(transaction)
    return _transaction_response(transaction)


def get_revenue(
    session: Session,
    *,
    since: datetime | None,
) -> RevenueResponse:
    statement = select(TransactionRecord)
    if since is not None:
        statement = statement.where(TransactionRecord.occurred_at >= since)

    rows = session.scalars(statement).all()
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "sales_count": 0,
            "refund_count": 0,
            "sales_minor_units": 0,
            "refunds_minor_units": 0,
        }
    )

    for row in rows:
        bucket = totals[row.currency]
        if row.kind == "sale":
            bucket["sales_count"] += 1
            bucket["sales_minor_units"] += row.amount_minor_units
        elif row.kind == "refund":
            bucket["refund_count"] += 1
            bucket["refunds_minor_units"] += row.amount_minor_units

    currencies = [
        RevenueCurrencySummary(
            currency=currency,
            sales_count=values["sales_count"],
            refund_count=values["refund_count"],
            sales_minor_units=values["sales_minor_units"],
            refunds_minor_units=values["refunds_minor_units"],
            net_revenue_minor_units=(
                values["sales_minor_units"] - values["refunds_minor_units"]
            ),
        )
        for currency, values in sorted(totals.items())
    ]
    return RevenueResponse(since=since, currencies=currencies)


def get_audit_events(
    session: Session,
    job_id: str,
) -> list[AuditEventResponse]:
    rows = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.job_id == job_id)
        .order_by(AuditEvent.id.asc())
    ).all()
    return [
        AuditEventResponse(
            id=row.id,
            job_id=row.job_id,
            event_type=row.event_type,
            actor=row.actor,
            payload=json.loads(row.payload_json or "{}"),
            created_at=row.created_at,
        )
        for row in rows
    ]
