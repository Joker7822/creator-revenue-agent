from __future__ import annotations

import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api_server.db import JobRecord, VerificationRecord
from api_server.repository import add_audit
from api_server.schemas import (
    ContentGenerateRequest,
    PolicyEvaluateRequest,
    VerificationResponse,
)


VALID_KINDS = {
    "age",
    "creator_consent",
    "real_person_consent",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def trusted_verification_required() -> bool:
    return os.getenv(
        "REQUIRE_TRUSTED_VERIFICATION",
        "true",
    ).lower() in {"1", "true", "yes", "on"}


def _response(record: VerificationRecord) -> VerificationResponse:
    return VerificationResponse(
        verification_id=record.id,
        subject_ref=record.subject_ref,
        kind=record.kind,
        status=record.status,
        source=record.source,
        source_record_ref=record.source_record_ref,
        age_years=record.age_years,
        created_by=record.created_by,
        created_at=record.created_at,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        revoked_by=record.revoked_by,
        revoke_reason=record.revoke_reason,
    )


def _is_active(record: VerificationRecord) -> bool:
    if record.status != "active" or record.revoked_at is not None:
        return False
    if record.expires_at is None:
        return True
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > utcnow()


def _require_record(
    session: Session,
    *,
    verification_id: str | None,
    subject_ref: str | None,
    kind: str,
) -> VerificationRecord:
    if not verification_id:
        raise HTTPException(
            status_code=409,
            detail=f"{kind} verification record required",
        )
    record = session.get(VerificationRecord, verification_id)
    if record is None:
        raise HTTPException(
            status_code=409,
            detail=f"{kind} verification record not found",
        )
    if record.kind != kind:
        raise HTTPException(
            status_code=409,
            detail=f"{kind} verification kind mismatch",
        )
    if not subject_ref or record.subject_ref != subject_ref:
        raise HTTPException(
            status_code=409,
            detail=f"{kind} verification subject mismatch",
        )
    if not _is_active(record):
        raise HTTPException(
            status_code=409,
            detail=f"{kind} verification record is not active",
        )
    return record


def create_verification_record(
    session: Session,
    *,
    subject_ref: str,
    kind: str,
    source: str,
    source_record_ref: str | None,
    age_years: int | None,
    expires_at: datetime | None,
    created_by: str,
) -> VerificationRecord:
    if kind not in VALID_KINDS:
        raise HTTPException(
            status_code=400,
            detail="invalid verification kind",
        )
    if kind == "age" and age_years is None:
        raise HTTPException(
            status_code=400,
            detail="age verification requires age_years",
        )
    if kind != "age" and age_years is not None:
        raise HTTPException(
            status_code=400,
            detail="age_years is only valid for age verification",
        )
    if expires_at is not None:
        normalized = expires_at
        if normalized.tzinfo is None:
            normalized = normalized.replace(tzinfo=timezone.utc)
        if normalized <= utcnow():
            raise HTTPException(
                status_code=400,
                detail="verification expiration must be in the future",
            )

    record = VerificationRecord(
        id=f"ver_{uuid4().hex}",
        subject_ref=subject_ref,
        kind=kind,
        status="active",
        source=source,
        source_record_ref=source_record_ref,
        age_years=age_years,
        created_by=created_by,
        expires_at=expires_at,
    )
    session.add(record)
    add_audit(
        session,
        job_id=None,
        event_type="verification_created",
        actor=created_by,
        payload={
            "verification_id": record.id,
            "subject_ref": subject_ref,
            "kind": kind,
            "source": source,
        },
    )
    session.flush()
    session.refresh(record)
    return record


def create_verification(
    session: Session,
    *,
    subject_ref: str,
    kind: str,
    source: str,
    source_record_ref: str | None,
    age_years: int | None,
    expires_at: datetime | None,
    created_by: str,
) -> VerificationResponse:
    record = create_verification_record(
        session,
        subject_ref=subject_ref,
        kind=kind,
        source=source,
        source_record_ref=source_record_ref,
        age_years=age_years,
        expires_at=expires_at,
        created_by=created_by,
    )
    session.commit()
    session.refresh(record)
    return _response(record)


def get_verification(
    session: Session,
    verification_id: str,
) -> VerificationResponse:
    record = session.get(VerificationRecord, verification_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="verification record not found",
        )
    return _response(record)


def revoke_verification_record(
    session: Session,
    *,
    record: VerificationRecord,
    actor: str,
    reason: str,
) -> VerificationRecord:
    if record.revoked_at is None:
        record.status = "revoked"
        record.revoked_at = utcnow()
        record.revoked_by = actor
        record.revoke_reason = reason

        jobs = session.scalars(
            select(JobRecord).where(
                or_(
                    JobRecord.age_verification_id == record.id,
                    JobRecord.consent_verification_id == record.id,
                    JobRecord.real_person_consent_verification_id
                    == record.id,
                )
            )
        ).all()
        for job in jobs:
            job.policy_allowed = False
            job.policy_reasons_json = (
                '["trusted_verification_revoked"]'
            )
            add_audit(
                session,
                job_id=job.id,
                event_type="verification_invalidated_job",
                actor=actor,
                payload={
                    "verification_id": record.id,
                    "reason": reason,
                },
            )

        add_audit(
            session,
            job_id=None,
            event_type="verification_revoked",
            actor=actor,
            payload={
                "verification_id": record.id,
                "reason": reason,
            },
        )
        session.flush()
    return record


def revoke_verification(
    session: Session,
    *,
    verification_id: str,
    actor: str,
    reason: str,
) -> VerificationResponse:
    record = session.get(VerificationRecord, verification_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="verification record not found",
        )
    record = revoke_verification_record(
        session,
        record=record,
        actor=actor,
        reason=reason,
    )
    session.commit()
    session.refresh(record)
    return _response(record)


def resolve_content_request(
    session: Session,
    request: ContentGenerateRequest,
) -> ContentGenerateRequest:
    has_any_reference = any(
        (
            request.age_verification_id,
            request.consent_verification_id,
            request.real_person_consent_verification_id,
        )
    )
    if not trusted_verification_required() and not has_any_reference:
        return request

    if not request.creator_ref:
        raise HTTPException(
            status_code=409,
            detail="creator_ref required for trusted verification",
        )

    age = _require_record(
        session,
        verification_id=request.age_verification_id,
        subject_ref=request.creator_ref,
        kind="age",
    )
    _require_record(
        session,
        verification_id=request.consent_verification_id,
        subject_ref=request.creator_ref,
        kind="creator_consent",
    )

    real_person_verified = False
    if request.depicts_real_person:
        _require_record(
            session,
            verification_id=request.real_person_consent_verification_id,
            subject_ref=request.creator_ref,
            kind="real_person_consent",
        )
        real_person_verified = True

    return request.model_copy(
        update={
            "creator_age": age.age_years,
            "age_verified": True,
            "consent_verified": True,
            "real_person_consent_verified": real_person_verified,
        }
    )


def _record_current(
    session: Session,
    *,
    verification_id: str | None,
    subject_ref: str | None,
    kind: str,
) -> VerificationRecord | None:
    if not verification_id or not subject_ref:
        return None
    record = session.get(VerificationRecord, verification_id)
    if (
        record is None
        or record.kind != kind
        or record.subject_ref != subject_ref
        or not _is_active(record)
    ):
        return None
    return record


def policy_request_for_job(
    session: Session,
    *,
    job: JobRecord,
    asset_ref: str | None,
) -> PolicyEvaluateRequest:
    has_trusted_refs = any(
        (
            job.age_verification_id,
            job.consent_verification_id,
            job.real_person_consent_verification_id,
        )
    )
    if not trusted_verification_required() and not has_trusted_refs:
        return PolicyEvaluateRequest(
            job_id=job.id,
            creator_age=job.creator_age,
            age_verified=job.age_verified,
            consent_verified=job.consent_verified,
            depicts_real_person=job.depicts_real_person,
            real_person_consent_verified=(
                job.real_person_consent_verified
            ),
            asset_ref=asset_ref,
        )

    age = _record_current(
        session,
        verification_id=job.age_verification_id,
        subject_ref=job.creator_ref,
        kind="age",
    )
    consent = _record_current(
        session,
        verification_id=job.consent_verification_id,
        subject_ref=job.creator_ref,
        kind="creator_consent",
    )
    real_person = _record_current(
        session,
        verification_id=job.real_person_consent_verification_id,
        subject_ref=job.creator_ref,
        kind="real_person_consent",
    )

    return PolicyEvaluateRequest(
        job_id=job.id,
        creator_age=age.age_years if age else None,
        age_verified=age is not None,
        consent_verified=consent is not None,
        depicts_real_person=job.depicts_real_person,
        real_person_consent_verified=(
            real_person is not None
            if job.depicts_real_person
            else False
        ),
        asset_ref=asset_ref,
    )


def assert_job_verifications_current(
    session: Session,
    job: JobRecord,
) -> None:
    has_trusted_refs = any(
        (
            job.age_verification_id,
            job.consent_verification_id,
            job.real_person_consent_verification_id,
        )
    )
    if not trusted_verification_required() and not has_trusted_refs:
        return

    _require_record(
        session,
        verification_id=job.age_verification_id,
        subject_ref=job.creator_ref,
        kind="age",
    )
    _require_record(
        session,
        verification_id=job.consent_verification_id,
        subject_ref=job.creator_ref,
        kind="creator_consent",
    )
    if job.depicts_real_person:
        _require_record(
            session,
            verification_id=job.real_person_consent_verification_id,
            subject_ref=job.creator_ref,
            kind="real_person_consent",
        )
