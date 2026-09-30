from __future__ import annotations

import json
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
    PublicationRecord,
)
from api_server.schemas import (
    ApprovalResponse,
    AuditEventResponse,
    ContentGenerateRequest,
    ContentGenerateResponse,
    PublicationResponse,
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
        real_person_consent_verified=(
            response.real_person_consent_verified
        ),
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
    job.policy_reasons_json = json.dumps(
        reasons,
        separators=(",", ":"),
    )

    add_audit(
        session,
        job_id=job_id,
        event_type="policy_evaluated",
        actor="system",
        payload={
            "allowed": allowed,
            "reasons": reasons,
        },
    )

    session.commit()
    session.refresh(job)
    return job


def _approval_response(
    record: ApprovalRecord,
) -> ApprovalResponse:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )

    if job.policy_allowed is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="policy approval required",
        )

    existing = session.get(ApprovalRecord, job_id)
    if existing is not None:
        return _approval_response(existing)

    now = utcnow()
    approval = ApprovalRecord(
        job_id=job_id,
        required=required,
        status=(
            "pending_review"
            if required
            else "approved"
        ),
        reviewer=None if required else "system",
        decided_at=None if required else now,
    )
    session.add(approval)

    add_audit(
        session,
        job_id=job_id,
        event_type="approval_created",
        actor="system",
        payload={
            "required": required,
            "status": approval.status,
        },
    )

    if not required:
        add_audit(
            session,
            job_id=job_id,
            event_type="approval_approved",
            actor="system",
            payload={
                "reason": "human_review_not_required",
            },
        )

    session.commit()
    session.refresh(approval)
    return _approval_response(approval)


def get_approval(
    session: Session,
    job_id: str,
) -> ApprovalResponse:
    approval = session.get(ApprovalRecord, job_id)
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="approval not found",
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="approval not found",
        )

    if approval.status != "pending_review":
        if approval.status == decision:
            return _approval_response(approval)

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
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


def _publication_response(
    record: PublicationRecord,
) -> PublicationResponse:
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )

    if job.policy_allowed is not True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="policy approval required",
        )

    approval = session.get(ApprovalRecord, job_id)
    if approval is None or approval.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="human approval required",
        )

    existing = session.scalar(
        select(PublicationRecord).where(
            PublicationRecord.job_id == job_id
        )
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


def get_publication(
    session: Session,
    job_id: str,
) -> PublicationResponse:
    record = session.scalar(
        select(PublicationRecord).where(
            PublicationRecord.job_id == job_id
        )
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="publication not found",
        )
    return _publication_response(record)


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
