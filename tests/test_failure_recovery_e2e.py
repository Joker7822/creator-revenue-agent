import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import delete

import api_server.audit_anchor as audit_anchor
from api_server.db import (
    AuditAnchorReceiptRecord,
    AuditChainState,
    AuditEvent,
    SessionLocal,
)
from api_server.main import app
from api_server.observability import operational_metrics


client = TestClient(app)

OLD_SECRET = "provider-old-secret-0000000000000000001"
NEW_SECRET = "provider-new-secret-0000000000000000002"
RECEIPT_KEY_ID = "test-anchor-receipt-2026-10"
RECEIPT_SECRET = (
    "anchor-receipt-secret-000000000000000001"
)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def webhook_body(payload: dict) -> bytes:
    return json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def webhook_headers(
    *,
    event_id: str,
    body: bytes,
    key_id: str,
    secret: str,
) -> dict[str, str]:
    timestamp = int(time.time())
    canonical = (
        (
            f"provider-a.{key_id}.{timestamp}."
            f"{event_id}."
        ).encode("utf-8")
        + body
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Verification-Provider": "provider-a",
        "X-Verification-Key-Id": key_id,
        "X-Verification-Event-Id": event_id,
        "X-Verification-Timestamp": str(timestamp),
        "X-Verification-Signature": f"v1={signature}",
        "Content-Type": "application/json",
    }


def verified_event(
    *,
    provider_record_ref: str,
    subject_ref: str,
    kind: str,
    age_years: int | None = None,
) -> dict:
    payload = {
        "event_type": "verification.verified",
        "provider_record_ref": provider_record_ref,
        "subject_ref": subject_ref,
        "kind": kind,
    }
    if age_years is not None:
        payload["age_years"] = age_years
    return payload


def send_webhook(
    payload: dict,
    *,
    event_id: str,
    key_id: str = "old",
    secret: str = OLD_SECRET,
):
    raw = webhook_body(payload)
    return client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=webhook_headers(
            event_id=event_id,
            body=raw,
            key_id=key_id,
            secret=secret,
        ),
    )


def content_payload(
    *,
    creator_ref: str,
    age_verification_id: str | None = None,
    consent_verification_id: str | None = None,
) -> dict:
    return {
        "campaign_type": "members_only_release",
        "target_segment": "subscribers",
        "price_cents": 1500,
        "creator_ref": creator_ref,
        "age_verification_id": age_verification_id,
        "consent_verification_id": consent_verification_id,
        "depicts_real_person": False,
    }


def create_basic_job() -> dict:
    response = client.post(
        "/v1/content/generate",
        headers=bearer("test-token"),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "creator_age": 24,
            "age_verified": True,
            "consent_verified": True,
            "depicts_real_person": False,
        },
    )
    assert response.status_code == 200
    return response.json()


def receipt_signature(receipt: dict) -> str:
    canonical = json.dumps(
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
            "version": "audit-anchor-receipt-v1",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(
        RECEIPT_SECRET.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()


class RecoverableWorm:
    def __init__(self) -> None:
        self.available = True
        self.latest: dict | None = None
        self.by_anchor: dict[str, dict] = {}

    def handler(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        if not self.available:
            raise httpx.ConnectError(
                "simulated WORM outage",
                request=request,
            )

        if (
            request.method == "POST"
            and request.url.path == "/v1/anchors"
        ):
            payload = json.loads(request.content)
            anchor_id = payload["anchor_id"]
            existing = self.by_anchor.get(anchor_id)
            if existing is not None:
                return httpx.Response(200, json=existing)

            receipt = {
                **payload,
                "receipt_id": f"receipt-{anchor_id}",
                "anchored_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "receipt_key_id": RECEIPT_KEY_ID,
            }
            receipt["receipt_signature"] = (
                receipt_signature(receipt)
            )
            self.by_anchor[anchor_id] = receipt
            self.latest = receipt
            return httpx.Response(201, json=receipt)

        if (
            request.method == "GET"
            and request.url.path == "/v1/anchors/latest"
        ):
            if self.latest is None:
                return httpx.Response(404)
            return httpx.Response(200, json=self.latest)

        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handler),
            headers={
                "Authorization": (
                    "Bearer test-audit-anchor-service-token"
                ),
                "Accept": "application/json",
            },
        )


def install_worm(
    monkeypatch,
    store: RecoverableWorm,
) -> None:
    monkeypatch.setattr(
        audit_anchor,
        "_http_client",
        store.client,
    )


def issue_anchor_jwt() -> str:
    response = client.post(
        "/v1/auth/credentials",
        headers=bearer("credential-admin-token"),
        json={
            "subject": "recovery-anchor-operator",
            "roles": ["audit_anchor_operator"],
            "ttl_seconds": 900,
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def set_readiness_production_flags(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SERVICE_AUTH_MODE", "jwt")
    monkeypatch.setenv(
        "REQUIRE_TRUSTED_VERIFICATION",
        "true",
    )
    monkeypatch.setenv(
        "PRODUCTION_REQUIRE_ROW_LOCKING_DATABASE",
        "false",
    )
    monkeypatch.setenv(
        "AUDIT_ANCHOR_MAX_AGE_SECONDS",
        "900",
    )
    monkeypatch.setenv(
        "AUDIT_ANCHOR_MAX_UNANCHORED_EVENTS",
        "100",
    )


def test_provider_absence_blocks_then_recovers_from_webhooks(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "REQUIRE_TRUSTED_VERIFICATION",
        "true",
    )
    creator_ref = "creator-provider-recovery"

    blocked = client.post(
        "/v1/content/generate",
        headers=bearer("test-token"),
        json=content_payload(
            creator_ref=creator_ref,
        ),
    )
    assert blocked.status_code == 409

    age = send_webhook(
        verified_event(
            provider_record_ref="age-recovery-1",
            subject_ref=creator_ref,
            kind="age",
            age_years=24,
        ),
        event_id="evt-age-recovery-1",
    )
    consent = send_webhook(
        verified_event(
            provider_record_ref="consent-recovery-1",
            subject_ref=creator_ref,
            kind="creator_consent",
        ),
        event_id="evt-consent-recovery-1",
    )
    assert age.status_code == 200
    assert consent.status_code == 200

    recovered = client.post(
        "/v1/content/generate",
        headers=bearer("test-token"),
        json=content_payload(
            creator_ref=creator_ref,
            age_verification_id=(
                age.json()["verification"]["verification_id"]
            ),
            consent_verification_id=(
                consent.json()["verification"]["verification_id"]
            ),
        ),
    )
    assert recovered.status_code == 200
    assert recovered.json()["age_verified"] is True
    assert recovered.json()["consent_verified"] is True
    assert recovered.json()["creator_age"] == 24


def test_failed_old_key_delivery_can_recover_with_new_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "VERIFICATION_WEBHOOK_KEYS_JSON",
        json.dumps(
            {
                "provider-a": {
                    "new": NEW_SECRET,
                }
            }
        ),
    )
    payload = verified_event(
        provider_record_ref="rotation-recovery-1",
        subject_ref="creator-rotation-recovery",
        kind="age",
        age_years=25,
    )
    event_id = "evt-rotation-recovery-1"

    rejected = send_webhook(
        payload,
        event_id=event_id,
        key_id="old",
        secret=OLD_SECRET,
    )
    assert rejected.status_code == 401

    recovered = send_webhook(
        payload,
        event_id=event_id,
        key_id="new",
        secret=NEW_SECRET,
    )
    assert recovered.status_code == 200
    assert recovered.json()["duplicate"] is False
    assert recovered.json()["key_id"] == "new"

    retry = send_webhook(
        payload,
        event_id=event_id,
        key_id="new",
        secret=NEW_SECRET,
    )
    assert retry.status_code == 200
    assert retry.json()["duplicate"] is True
    assert (
        retry.json()["verification"]["verification_id"]
        == recovered.json()["verification"]["verification_id"]
    )


def test_worm_outage_fails_closed_then_recovers_readiness(
    monkeypatch,
) -> None:
    create_basic_job()
    anchor_jwt = issue_anchor_jwt()

    store = RecoverableWorm()
    store.available = False
    install_worm(monkeypatch, store)
    set_readiness_production_flags(monkeypatch)

    unavailable = client.get("/ready")
    assert unavailable.status_code == 503
    anchor_check = next(
        row
        for row in unavailable.json()["checks"]
        if row["name"] == "audit_anchor_freshness"
    )
    assert anchor_check["ready"] is False
    assert "unavailable" in anchor_check["detail"]

    store.available = True
    anchored = client.post(
        "/v1/audit/anchors",
        headers=bearer(anchor_jwt),
    )
    assert anchored.status_code == 200

    recovered = client.get("/ready")
    assert recovered.status_code == 200
    assert recovered.json()["ready"] is True

    ops = client.get(
        "/v1/ops/status",
        headers=bearer(anchor_jwt),
    )
    assert ops.status_code == 200
    assert (
        ops.json()["incident_signals"]["readiness_failures"]
        >= 1
    )


def test_process_local_reset_preserves_webhook_idempotency() -> None:
    payload = verified_event(
        provider_record_ref="restart-recovery-1",
        subject_ref="creator-restart-recovery",
        kind="age",
        age_years=26,
    )
    event_id = "evt-restart-recovery-1"

    first = send_webhook(
        payload,
        event_id=event_id,
    )
    assert first.status_code == 200
    verification_id = (
        first.json()["verification"]["verification_id"]
    )

    operational_metrics.reset()

    with TestClient(app) as restarted_client:
        raw = webhook_body(payload)
        second = restarted_client.post(
            "/v1/webhooks/verifications",
            content=raw,
            headers=webhook_headers(
                event_id=event_id,
                body=raw,
                key_id="old",
                secret=OLD_SECRET,
            ),
        )

    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert (
        second.json()["verification"]["verification_id"]
        == verification_id
    )


def test_valid_database_rollback_fails_production_readiness(
    monkeypatch,
) -> None:
    store = RecoverableWorm()
    install_worm(monkeypatch, store)

    job = create_basic_job()
    with SessionLocal() as session:
        state = session.get(AuditChainState, 1)
        assert state is not None
        old_state = {
            "last_event_id": state.last_event_id,
            "last_hash": state.last_hash,
            "hash_key_id": state.hash_key_id,
            "state_hash": state.state_hash,
            "updated_at": state.updated_at,
        }

    policy = client.post(
        "/v1/policy/evaluate",
        headers=bearer("test-token"),
        json={"job_id": job["job_id"]},
    )
    assert policy.status_code == 200

    anchored = client.post(
        "/v1/audit/anchors",
        headers=bearer("audit-anchor-token"),
    )
    assert anchored.status_code == 200
    assert (
        anchored.json()["head_event_id"]
        > old_state["last_event_id"]
    )

    with SessionLocal() as session:
        session.execute(delete(AuditAnchorReceiptRecord))
        session.execute(
            delete(AuditEvent).where(
                AuditEvent.id > old_state["last_event_id"]
            )
        )
        state = session.get(AuditChainState, 1)
        assert state is not None
        state.last_event_id = old_state["last_event_id"]
        state.last_hash = old_state["last_hash"]
        state.hash_key_id = old_state["hash_key_id"]
        state.state_hash = old_state["state_hash"]
        state.updated_at = old_state["updated_at"]
        session.commit()

    set_readiness_production_flags(monkeypatch)
    response = client.get("/ready")
    assert response.status_code == 503
    anchor_check = next(
        row
        for row in response.json()["checks"]
        if row["name"] == "audit_anchor_freshness"
    )
    assert anchor_check["ready"] is False
    assert "rollback_detected" in anchor_check["detail"]
