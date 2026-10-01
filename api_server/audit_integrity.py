from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api_server.db import AuditChainState, AuditEvent
from api_server.schemas import AuditIntegrityResponse


ROOT_HASH = "0" * 64
CHAIN_STATE_ID = 1
LEGACY_KEY_ID = "legacy-sha256-v1"
EVENT_VERSION = "audit-event-v1"
HEAD_VERSION = "audit-head-v1"


class AuditKeyUnavailable(Exception):
    pass


def _audit_keys() -> dict[str, str]:
    raw = os.getenv("AUDIT_HASH_KEYS_JSON", "").strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit hash keys are not configured",
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit hash key configuration is invalid",
        ) from exc

    if (
        not isinstance(data, dict)
        or not data
        or not all(
            isinstance(key_id, str)
            and key_id
            and len(key_id) <= 120
            and isinstance(secret_value, str)
            and len(secret_value) >= 32
            for key_id, secret_value in data.items()
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit hash key configuration is invalid",
        )
    return data


def _active_key_id() -> str:
    key_id = os.getenv("AUDIT_HASH_ACTIVE_KID", "").strip()
    keys = _audit_keys()
    if not key_id or key_id not in keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="active audit hash key is invalid",
        )
    return key_id


def _canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    value = value.replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


def _digest(
    *,
    key_id: str,
    canonical: bytes,
) -> str:
    if key_id == LEGACY_KEY_ID:
        return hashlib.sha256(canonical).hexdigest()

    secret_value = _audit_keys().get(key_id)
    if secret_value is None:
        raise AuditKeyUnavailable(key_id)
    return hmac.new(
        secret_value.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()


def compute_event_hash(
    *,
    event_id: int,
    job_id: str | None,
    event_type: str,
    actor: str | None,
    payload_json: str,
    created_at: datetime,
    previous_hash: str,
    hash_key_id: str,
) -> str:
    canonical = json.dumps(
        {
            "actor": actor,
            "created_at": _canonical_timestamp(created_at),
            "event_type": event_type,
            "hash_key_id": hash_key_id,
            "id": event_id,
            "job_id": job_id,
            "payload_json": payload_json,
            "previous_hash": previous_hash,
            "version": EVENT_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _digest(
        key_id=hash_key_id,
        canonical=canonical,
    )


def compute_head_hash(
    *,
    last_event_id: int | None,
    last_hash: str,
    hash_key_id: str,
) -> str:
    canonical = json.dumps(
        {
            "hash_key_id": hash_key_id,
            "last_event_id": last_event_id,
            "last_hash": last_hash,
            "version": HEAD_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _digest(
        key_id=hash_key_id,
        canonical=canonical,
    )


def _locked_chain_state(
    session: Session,
) -> AuditChainState:
    state = session.scalar(
        select(AuditChainState)
        .where(AuditChainState.id == CHAIN_STATE_ID)
        .with_for_update()
    )
    if state is not None:
        return state

    event_count = session.scalar(
        select(func.count(AuditEvent.id))
    )
    if event_count:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit chain state missing for existing events",
        )

    key_id = _active_key_id()
    state = AuditChainState(
        id=CHAIN_STATE_ID,
        last_event_id=None,
        last_hash=ROOT_HASH,
        hash_key_id=key_id,
        state_hash=compute_head_hash(
            last_event_id=None,
            last_hash=ROOT_HASH,
            hash_key_id=key_id,
        ),
    )
    session.add(state)
    session.flush()
    return state


def append_audit_event(
    session: Session,
    *,
    job_id: str | None,
    event_type: str,
    actor: str | None,
    payload_json: str,
) -> AuditEvent:
    state = _locked_chain_state(session)
    previous_hash = state.last_hash or ROOT_HASH
    key_id = _active_key_id()

    event = AuditEvent(
        job_id=job_id,
        event_type=event_type,
        actor=actor,
        payload_json=payload_json,
        previous_hash=previous_hash,
        hash_key_id=key_id,
        event_hash="",
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    session.flush()

    event.event_hash = compute_event_hash(
        event_id=event.id,
        job_id=event.job_id,
        event_type=event.event_type,
        actor=event.actor,
        payload_json=event.payload_json,
        created_at=event.created_at,
        previous_hash=event.previous_hash,
        hash_key_id=event.hash_key_id,
    )
    state.last_event_id = event.id
    state.last_hash = event.event_hash
    state.hash_key_id = key_id
    state.state_hash = compute_head_hash(
        last_event_id=event.id,
        last_hash=event.event_hash,
        hash_key_id=key_id,
    )
    session.flush()
    return event


def _invalid(
    *,
    checked_events: int,
    head_event_id: int | None,
    head_hash: str,
    event_id: int | None,
    reason: str,
) -> AuditIntegrityResponse:
    return AuditIntegrityResponse(
        valid=False,
        checked_events=checked_events,
        head_event_id=head_event_id,
        head_hash=head_hash,
        first_invalid_event_id=event_id,
        reason=reason,
    )


def verify_audit_chain(
    session: Session,
) -> AuditIntegrityResponse:
    rows = session.scalars(
        select(AuditEvent).order_by(AuditEvent.id.asc())
    ).all()
    expected_previous = ROOT_HASH
    last_event_id: int | None = None
    checked = 0

    for row in rows:
        checked += 1
        if row.previous_hash != expected_previous:
            return _invalid(
                checked_events=checked,
                head_event_id=last_event_id,
                head_hash=expected_previous,
                event_id=row.id,
                reason="previous_hash_mismatch",
            )

        try:
            expected_hash = compute_event_hash(
                event_id=row.id,
                job_id=row.job_id,
                event_type=row.event_type,
                actor=row.actor,
                payload_json=row.payload_json,
                created_at=row.created_at,
                previous_hash=row.previous_hash,
                hash_key_id=row.hash_key_id,
            )
        except (AuditKeyUnavailable, HTTPException):
            return _invalid(
                checked_events=checked,
                head_event_id=last_event_id,
                head_hash=expected_previous,
                event_id=row.id,
                reason="hash_key_unavailable",
            )

        if row.event_hash != expected_hash:
            return _invalid(
                checked_events=checked,
                head_event_id=last_event_id,
                head_hash=expected_previous,
                event_id=row.id,
                reason="event_hash_mismatch",
            )

        expected_previous = row.event_hash
        last_event_id = row.id

    state = session.get(AuditChainState, CHAIN_STATE_ID)
    if state is None:
        return _invalid(
            checked_events=checked,
            head_event_id=last_event_id,
            head_hash=expected_previous,
            event_id=None,
            reason="chain_state_missing",
        )

    if (
        state.last_event_id != last_event_id
        or state.last_hash != expected_previous
    ):
        return _invalid(
            checked_events=checked,
            head_event_id=last_event_id,
            head_hash=expected_previous,
            event_id=None,
            reason="chain_head_mismatch",
        )

    try:
        expected_state_hash = compute_head_hash(
            last_event_id=state.last_event_id,
            last_hash=state.last_hash,
            hash_key_id=state.hash_key_id,
        )
    except (AuditKeyUnavailable, HTTPException):
        return _invalid(
            checked_events=checked,
            head_event_id=last_event_id,
            head_hash=expected_previous,
            event_id=None,
            reason="head_hash_key_unavailable",
        )

    if state.state_hash != expected_state_hash:
        return _invalid(
            checked_events=checked,
            head_event_id=last_event_id,
            head_hash=expected_previous,
            event_id=None,
            reason="chain_state_hash_mismatch",
        )

    return AuditIntegrityResponse(
        valid=True,
        checked_events=checked,
        head_event_id=last_event_id,
        head_hash=expected_previous,
        first_invalid_event_id=None,
        reason=None,
    )
