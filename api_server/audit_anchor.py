from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.audit_integrity import (
    CHAIN_STATE_ID,
    compute_head_hash,
    verify_audit_chain,
)
from api_server.observability import outbound_trace_headers
from api_server.db import (
    AuditAnchorReceiptRecord,
    AuditChainState,
    AuditEvent,
)
from api_server.secret_source import read_secret_setting
from api_server.schemas import (
    AuditAnchorFreshnessResponse,
    AuditAnchorReceiptResponse,
    AuditAnchorVerificationResponse,
)


RECEIPT_VERSION = "audit-anchor-receipt-v1"


def _base_url() -> str:
    value = os.getenv("AUDIT_ANCHOR_BASE_URL", "").strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor service is not configured",
        )
    return value.rstrip("/")


def _token() -> str:
    value = read_secret_setting("AUDIT_ANCHOR_TOKEN")
    if not value:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor token is not configured",
        )
    return value


def _namespace() -> str:
    value = os.getenv(
        "AUDIT_ANCHOR_NAMESPACE",
        "creator-revenue-agent",
    ).strip()
    if not value or len(value) > 120:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor namespace is invalid",
        )
    return value


def _max_anchor_age_seconds() -> int:
    raw = os.getenv(
        "AUDIT_ANCHOR_MAX_AGE_SECONDS",
        "900",
    )
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor max age is invalid",
        ) from exc
    if value < 60 or value > 86400:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor max age is invalid",
        )
    return value


def _max_unanchored_events() -> int:
    raw = os.getenv(
        "AUDIT_ANCHOR_MAX_UNANCHORED_EVENTS",
        "100",
    )
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor event gap is invalid",
        ) from exc
    if value < 0 or value > 100000:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor event gap is invalid",
        )
    return value


def _enforce_rollout_freshness() -> bool:
    return os.getenv(
        "ENFORCE_AUDIT_ANCHOR_FRESHNESS_ON_ROLLOUT",
        "true",
    ).lower() in {"1", "true", "yes", "on"}


def _timeout_seconds() -> float:
    raw = os.getenv("AUDIT_ANCHOR_TIMEOUT_SECONDS", "5")
    try:
        value = float(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor timeout is invalid",
        ) from exc
    if value <= 0 or value > 30:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor timeout is invalid",
        )
    return value


def _receipt_keys() -> dict[str, str]:
    raw = read_secret_setting(
        "AUDIT_ANCHOR_RECEIPT_KEYS_JSON",
    )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor receipt keys are not configured",
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="audit anchor receipt key configuration is invalid",
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
            detail="audit anchor receipt key configuration is invalid",
        )
    return data


def _http_client() -> httpx.Client:
    return httpx.Client(
        timeout=_timeout_seconds(),
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/json",
            **outbound_trace_headers(),
        },
    )


def _receipt_canonical(receipt: dict) -> bytes:
    return json.dumps(
        {
            "anchor_id": receipt["anchor_id"],
            "anchored_at": receipt["anchored_at"],
            "head_event_id": receipt["head_event_id"],
            "head_hash": receipt["head_hash"],
            "head_hash_key_id": receipt["head_hash_key_id"],
            "head_state_hash": receipt["head_state_hash"],
            "namespace": receipt["namespace"],
            "receipt_id": receipt["receipt_id"],
            "receipt_key_id": receipt["receipt_key_id"],
            "requested_by": receipt["requested_by"],
            "version": RECEIPT_VERSION,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _verify_receipt_signature(receipt: dict) -> None:
    key_id = receipt.get("receipt_key_id")
    signature = receipt.get("receipt_signature")
    if (
        not isinstance(key_id, str)
        or not isinstance(signature, str)
        or len(signature) != 64
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor receipt is malformed",
        )

    secret_value = _receipt_keys().get(key_id)
    if secret_value is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor receipt key is not trusted",
        )

    try:
        expected = hmac.new(
            secret_value.encode("utf-8"),
            _receipt_canonical(receipt),
            hashlib.sha256,
        ).hexdigest()
    except (KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor receipt is malformed",
        ) from exc

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor receipt signature is invalid",
        )


def _parse_receipt(data: object) -> AuditAnchorReceiptResponse:
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor receipt is malformed",
        )

    _verify_receipt_signature(data)
    try:
        return AuditAnchorReceiptResponse.model_validate(data)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor receipt is malformed",
        ) from exc


def _anchor_id(
    *,
    namespace: str,
    head_event_id: int | None,
    head_hash: str,
    head_state_hash: str,
) -> str:
    material = (
        f"{namespace}:{head_event_id}:{head_hash}:"
        f"{head_state_hash}"
    ).encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    return f"anc_{digest[:40]}"


def _post_anchor(payload: dict) -> AuditAnchorReceiptResponse:
    try:
        with _http_client() as client:
            response = client.post(
                f"{_base_url()}/v1/anchors",
                json=payload,
                headers={
                    "Idempotency-Key": payload["anchor_id"],
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor service unavailable",
        ) from exc

    if response.status_code not in {200, 201}:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor service rejected anchor",
        )
    return _parse_receipt(response.json())


def _get_latest_anchor() -> AuditAnchorReceiptResponse | None:
    namespace = _namespace()
    try:
        with _http_client() as client:
            response = client.get(
                (
                    f"{_base_url()}/v1/anchors/latest"
                    f"?namespace={quote(namespace, safe='')}"
                )
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor service unavailable",
        ) from exc

    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor service rejected lookup",
        )
    return _parse_receipt(response.json())


def create_audit_anchor(
    session: Session,
    *,
    actor: str,
) -> AuditAnchorReceiptResponse:
    integrity = verify_audit_chain(session)
    if not integrity.valid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="local audit chain integrity check failed",
        )

    state = session.get(AuditChainState, CHAIN_STATE_ID)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="audit chain state missing",
        )

    namespace = _namespace()
    anchor_id = _anchor_id(
        namespace=namespace,
        head_event_id=state.last_event_id,
        head_hash=state.last_hash,
        head_state_hash=state.state_hash,
    )
    payload = {
        "namespace": namespace,
        "anchor_id": anchor_id,
        "head_event_id": state.last_event_id,
        "head_hash": state.last_hash,
        "head_state_hash": state.state_hash,
        "head_hash_key_id": state.hash_key_id,
        "requested_by": actor,
    }
    receipt = _post_anchor(payload)

    if (
        receipt.namespace != namespace
        or receipt.anchor_id != anchor_id
        or receipt.head_event_id != state.last_event_id
        or receipt.head_hash != state.last_hash
        or receipt.head_state_hash != state.state_hash
        or receipt.head_hash_key_id != state.hash_key_id
        or receipt.requested_by != actor
    ):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="audit anchor receipt does not match request",
        )

    existing = session.scalar(
        select(AuditAnchorReceiptRecord).where(
            AuditAnchorReceiptRecord.anchor_id == anchor_id
        )
    )
    if existing is None:
        session.add(
            AuditAnchorReceiptRecord(
                id=f"ar_{uuid4().hex}",
                anchor_id=receipt.anchor_id,
                namespace=receipt.namespace,
                head_event_id=receipt.head_event_id,
                head_hash=receipt.head_hash,
                head_state_hash=receipt.head_state_hash,
                head_hash_key_id=receipt.head_hash_key_id,
                requested_by=receipt.requested_by,
                remote_receipt_id=receipt.receipt_id,
                remote_receipt_key_id=receipt.receipt_key_id,
                remote_receipt_signature=(
                    receipt.receipt_signature
                ),
                anchored_at=receipt.anchored_at,
                recorded_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    return receipt


def verify_external_audit_anchor(
    session: Session,
) -> AuditAnchorVerificationResponse:
    local = verify_audit_chain(session)
    if not local.valid:
        return AuditAnchorVerificationResponse(
            valid=False,
            status="local_chain_invalid",
            namespace=_namespace(),
            anchor_id=None,
            anchor_event_id=None,
            local_event_id=local.head_event_id,
            anchor_head_hash=None,
            local_head_hash=local.head_hash,
            anchored_at=None,
            reason=local.reason,
        )

    receipt = _get_latest_anchor()
    if receipt is None:
        return AuditAnchorVerificationResponse(
            valid=False,
            status="external_anchor_missing",
            namespace=_namespace(),
            anchor_id=None,
            anchor_event_id=None,
            local_event_id=local.head_event_id,
            anchor_head_hash=None,
            local_head_hash=local.head_hash,
            anchored_at=None,
            reason="no external audit anchor exists",
        )

    if receipt.namespace != _namespace():
        return AuditAnchorVerificationResponse(
            valid=False,
            status="anchor_mismatch",
            namespace=_namespace(),
            anchor_id=receipt.anchor_id,
            anchor_event_id=receipt.head_event_id,
            local_event_id=local.head_event_id,
            anchor_head_hash=receipt.head_hash,
            local_head_hash=local.head_hash,
            anchored_at=receipt.anchored_at,
            reason="anchor namespace mismatch",
        )

    local_position = local.head_event_id or 0
    anchor_position = receipt.head_event_id or 0
    if anchor_position > local_position:
        return AuditAnchorVerificationResponse(
            valid=False,
            status="rollback_detected",
            namespace=receipt.namespace,
            anchor_id=receipt.anchor_id,
            anchor_event_id=receipt.head_event_id,
            local_event_id=local.head_event_id,
            anchor_head_hash=receipt.head_hash,
            local_head_hash=local.head_hash,
            anchored_at=receipt.anchored_at,
            reason="external anchor is ahead of local audit chain",
        )

    if receipt.head_event_id is None:
        anchored_event_hash = "0" * 64
    else:
        anchored_event = session.get(
            AuditEvent,
            receipt.head_event_id,
        )
        if anchored_event is None:
            return AuditAnchorVerificationResponse(
                valid=False,
                status="rollback_detected",
                namespace=receipt.namespace,
                anchor_id=receipt.anchor_id,
                anchor_event_id=receipt.head_event_id,
                local_event_id=local.head_event_id,
                anchor_head_hash=receipt.head_hash,
                local_head_hash=local.head_hash,
                anchored_at=receipt.anchored_at,
                reason="anchored audit event is missing locally",
            )
        anchored_event_hash = anchored_event.event_hash

    if anchored_event_hash != receipt.head_hash:
        return AuditAnchorVerificationResponse(
            valid=False,
            status="anchor_mismatch",
            namespace=receipt.namespace,
            anchor_id=receipt.anchor_id,
            anchor_event_id=receipt.head_event_id,
            local_event_id=local.head_event_id,
            anchor_head_hash=receipt.head_hash,
            local_head_hash=local.head_hash,
            anchored_at=receipt.anchored_at,
            reason="anchored event hash mismatch",
        )

    try:
        expected_state_hash = compute_head_hash(
            last_event_id=receipt.head_event_id,
            last_hash=receipt.head_hash,
            hash_key_id=receipt.head_hash_key_id,
        )
    except Exception:
        return AuditAnchorVerificationResponse(
            valid=False,
            status="anchor_mismatch",
            namespace=receipt.namespace,
            anchor_id=receipt.anchor_id,
            anchor_event_id=receipt.head_event_id,
            local_event_id=local.head_event_id,
            anchor_head_hash=receipt.head_hash,
            local_head_hash=local.head_hash,
            anchored_at=receipt.anchored_at,
            reason="anchored head key is unavailable",
        )

    if expected_state_hash != receipt.head_state_hash:
        return AuditAnchorVerificationResponse(
            valid=False,
            status="anchor_mismatch",
            namespace=receipt.namespace,
            anchor_id=receipt.anchor_id,
            anchor_event_id=receipt.head_event_id,
            local_event_id=local.head_event_id,
            anchor_head_hash=receipt.head_hash,
            local_head_hash=local.head_hash,
            anchored_at=receipt.anchored_at,
            reason="anchored chain-state hash mismatch",
        )

    status_value = (
        "in_sync"
        if anchor_position == local_position
        else "local_ahead"
    )
    return AuditAnchorVerificationResponse(
        valid=True,
        status=status_value,
        namespace=receipt.namespace,
        anchor_id=receipt.anchor_id,
        anchor_event_id=receipt.head_event_id,
        local_event_id=local.head_event_id,
        anchor_head_hash=receipt.head_hash,
        local_head_hash=local.head_hash,
        anchored_at=receipt.anchored_at,
        reason=None,
    )



def audit_anchor_freshness(
    session: Session,
) -> AuditAnchorFreshnessResponse:
    verification = verify_external_audit_anchor(session)
    max_age = _max_anchor_age_seconds()
    max_events = _max_unanchored_events()

    local_position = verification.local_event_id or 0
    anchor_position = verification.anchor_event_id or 0
    unanchored_events = max(
        0,
        local_position - anchor_position,
    )

    age_seconds: int | None = None
    if verification.anchored_at is not None:
        anchored_at = verification.anchored_at
        if anchored_at.tzinfo is None:
            anchored_at = anchored_at.replace(
                tzinfo=timezone.utc
            )
        delta = datetime.now(timezone.utc) - anchored_at
        age_seconds = int(delta.total_seconds())
        if age_seconds < -300:
            return AuditAnchorFreshnessResponse(
                fresh=False,
                verification_status=verification.status,
                anchor_event_id=verification.anchor_event_id,
                local_event_id=verification.local_event_id,
                unanchored_events=unanchored_events,
                anchored_at=verification.anchored_at,
                age_seconds=age_seconds,
                max_age_seconds=max_age,
                max_unanchored_events=max_events,
                reason="external anchor timestamp is too far in the future",
            )
        age_seconds = max(0, age_seconds)

    if not verification.valid:
        return AuditAnchorFreshnessResponse(
            fresh=False,
            verification_status=verification.status,
            anchor_event_id=verification.anchor_event_id,
            local_event_id=verification.local_event_id,
            unanchored_events=unanchored_events,
            anchored_at=verification.anchored_at,
            age_seconds=age_seconds,
            max_age_seconds=max_age,
            max_unanchored_events=max_events,
            reason=verification.reason,
        )

    if age_seconds is None:
        return AuditAnchorFreshnessResponse(
            fresh=False,
            verification_status=verification.status,
            anchor_event_id=verification.anchor_event_id,
            local_event_id=verification.local_event_id,
            unanchored_events=unanchored_events,
            anchored_at=verification.anchored_at,
            age_seconds=None,
            max_age_seconds=max_age,
            max_unanchored_events=max_events,
            reason="external anchor timestamp missing",
        )

    if age_seconds > max_age:
        return AuditAnchorFreshnessResponse(
            fresh=False,
            verification_status=verification.status,
            anchor_event_id=verification.anchor_event_id,
            local_event_id=verification.local_event_id,
            unanchored_events=unanchored_events,
            anchored_at=verification.anchored_at,
            age_seconds=age_seconds,
            max_age_seconds=max_age,
            max_unanchored_events=max_events,
            reason="external anchor is too old",
        )

    if unanchored_events > max_events:
        return AuditAnchorFreshnessResponse(
            fresh=False,
            verification_status=verification.status,
            anchor_event_id=verification.anchor_event_id,
            local_event_id=verification.local_event_id,
            unanchored_events=unanchored_events,
            anchored_at=verification.anchored_at,
            age_seconds=age_seconds,
            max_age_seconds=max_age,
            max_unanchored_events=max_events,
            reason="too many unanchored audit events",
        )

    return AuditAnchorFreshnessResponse(
        fresh=True,
        verification_status=verification.status,
        anchor_event_id=verification.anchor_event_id,
        local_event_id=verification.local_event_id,
        unanchored_events=unanchored_events,
        anchored_at=verification.anchored_at,
        age_seconds=age_seconds,
        max_age_seconds=max_age,
        max_unanchored_events=max_events,
        reason=None,
    )


def assert_audit_anchor_fresh(
    session: Session,
) -> None:
    if not _enforce_rollout_freshness():
        return

    result = audit_anchor_freshness(session)
    if not result.fresh:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "fresh external audit anchor required for rollout: "
                f"{result.reason or result.verification_status}"
            ),
        )
