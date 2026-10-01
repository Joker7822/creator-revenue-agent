import hashlib
import hmac
import json
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


client = TestClient(app)
RECEIPT_KEY_ID = "test-anchor-receipt-2026-10"
RECEIPT_SECRET = (
    "anchor-receipt-secret-000000000000000001"
)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_job() -> dict:
    response = client.post(
        "/v1/content/generate",
        headers=bearer("test-token"),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "creator_age": 21,
            "age_verified": True,
            "consent_verified": True,
            "depicts_real_person": False,
        },
    )
    assert response.status_code == 200
    return response.json()


def add_policy_event(job: dict) -> None:
    response = client.post(
        "/v1/policy/evaluate",
        headers=bearer("test-token"),
        json={"job_id": job["job_id"]},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def _receipt_signature(receipt: dict) -> str:
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


class WormStore:
    def __init__(self) -> None:
        self.by_anchor: dict[str, dict] = {}
        self.latest_by_namespace: dict[str, dict] = {}
        self.post_count = 0
        self.bad_signature = False

    def handler(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.headers["authorization"] == (
            "Bearer test-audit-anchor-service-token"
        )

        if (
            request.method == "POST"
            and request.url.path == "/v1/anchors"
        ):
            self.post_count += 1
            payload = json.loads(request.content)
            anchor_id = payload["anchor_id"]
            existing = self.by_anchor.get(anchor_id)
            if existing is not None:
                return httpx.Response(
                    200,
                    json=existing,
                )

            receipt = {
                **payload,
                "receipt_id": f"receipt-{anchor_id}",
                "anchored_at": (
                    datetime.now(timezone.utc).isoformat()
                ),
                "receipt_key_id": RECEIPT_KEY_ID,
            }
            receipt["receipt_signature"] = (
                "0" * 64
                if self.bad_signature
                else _receipt_signature(receipt)
            )
            self.by_anchor[anchor_id] = receipt
            self.latest_by_namespace[
                payload["namespace"]
            ] = receipt
            return httpx.Response(201, json=receipt)

        if (
            request.method == "GET"
            and request.url.path == "/v1/anchors/latest"
        ):
            namespace = request.url.params.get("namespace")
            receipt = self.latest_by_namespace.get(namespace)
            if receipt is None:
                return httpx.Response(404)
            return httpx.Response(200, json=receipt)

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
    store: WormStore,
) -> None:
    monkeypatch.setattr(
        audit_anchor,
        "_http_client",
        store.client,
    )


def test_anchor_round_trip_is_in_sync(
    monkeypatch,
) -> None:
    store = WormStore()
    install_worm(monkeypatch, store)
    create_job()

    anchored = client.post(
        "/v1/audit/anchors",
        headers=bearer("audit-anchor-token"),
    )
    assert anchored.status_code == 200
    receipt = anchored.json()
    assert receipt["head_event_id"] is not None
    assert receipt["requested_by"] == "audit-anchor-service"
    assert len(receipt["receipt_signature"]) == 64

    verified = client.get(
        "/v1/audit/anchors/verify",
        headers=bearer("test-token"),
    )
    assert verified.status_code == 200
    data = verified.json()
    assert data["valid"] is True
    assert data["status"] == "in_sync"
    assert data["anchor_event_id"] == receipt["head_event_id"]
    assert data["local_event_id"] == receipt["head_event_id"]


def test_anchor_is_idempotent_for_same_head(
    monkeypatch,
) -> None:
    store = WormStore()
    install_worm(monkeypatch, store)
    create_job()

    first = client.post(
        "/v1/audit/anchors",
        headers=bearer("audit-anchor-token"),
    )
    second = client.post(
        "/v1/audit/anchors",
        headers=bearer("audit-anchor-token"),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["anchor_id"] == second.json()["anchor_id"]
    assert first.json()["receipt_id"] == second.json()["receipt_id"]

    with SessionLocal() as session:
        receipts = session.query(
            AuditAnchorReceiptRecord
        ).all()
        assert len(receipts) == 1


def test_verify_allows_local_chain_ahead(
    monkeypatch,
) -> None:
    store = WormStore()
    install_worm(monkeypatch, store)
    job = create_job()

    anchored = client.post(
        "/v1/audit/anchors",
        headers=bearer("audit-anchor-token"),
    )
    assert anchored.status_code == 200
    anchor_event_id = anchored.json()["head_event_id"]

    add_policy_event(job)

    verified = client.get(
        "/v1/audit/anchors/verify",
        headers=bearer("test-token"),
    )
    assert verified.status_code == 200
    data = verified.json()
    assert data["valid"] is True
    assert data["status"] == "local_ahead"
    assert data["anchor_event_id"] == anchor_event_id
    assert data["local_event_id"] > anchor_event_id


def test_external_anchor_detects_valid_database_rollback(
    monkeypatch,
) -> None:
    store = WormStore()
    install_worm(monkeypatch, store)
    job = create_job()

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

    add_policy_event(job)

    anchored = client.post(
        "/v1/audit/anchors",
        headers=bearer("audit-anchor-token"),
    )
    assert anchored.status_code == 200
    anchored_event_id = anchored.json()["head_event_id"]
    assert anchored_event_id > old_state["last_event_id"]

    with SessionLocal() as session:
        session.execute(
            delete(AuditAnchorReceiptRecord)
        )
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

    local = client.get(
        "/v1/audit/integrity",
        headers=bearer("test-token"),
    )
    assert local.status_code == 200
    assert local.json()["valid"] is True
    assert local.json()["head_event_id"] == (
        old_state["last_event_id"]
    )

    external = client.get(
        "/v1/audit/anchors/verify",
        headers=bearer("test-token"),
    )
    assert external.status_code == 200
    data = external.json()
    assert data["valid"] is False
    assert data["status"] == "rollback_detected"
    assert data["anchor_event_id"] == anchored_event_id
    assert data["local_event_id"] == (
        old_state["last_event_id"]
    )


def test_invalid_external_receipt_signature_is_rejected(
    monkeypatch,
) -> None:
    store = WormStore()
    store.bad_signature = True
    install_worm(monkeypatch, store)
    create_job()

    response = client.post(
        "/v1/audit/anchors",
        headers=bearer("audit-anchor-token"),
    )
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "audit anchor receipt signature is invalid"
    )


def test_anchor_creation_requires_operator_role(
    monkeypatch,
) -> None:
    store = WormStore()
    install_worm(monkeypatch, store)
    create_job()

    response = client.post(
        "/v1/audit/anchors",
        headers=bearer("reader-token"),
    )
    assert response.status_code == 403


def test_missing_external_anchor_is_reported(
    monkeypatch,
) -> None:
    store = WormStore()
    install_worm(monkeypatch, store)
    create_job()

    response = client.get(
        "/v1/audit/anchors/verify",
        headers=bearer("test-token"),
    )
    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert response.json()["status"] == (
        "external_anchor_missing"
    )
