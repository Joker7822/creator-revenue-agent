import hashlib
import hmac
import json

from fastapi.testclient import TestClient

import audit_anchor_service.main as anchor


TOKEN = "anchor-token-" + "a" * 40
KEY_ID = "audit-anchor-receipt-2026-10"
KEY = "receipt-secret-" + "b" * 40
NAMESPACE = "creator-revenue-agent-production"


def payload(anchor_id: str = "anc_" + "1" * 40) -> dict:
    return {
        "namespace": NAMESPACE,
        "anchor_id": anchor_id,
        "head_event_id": 42,
        "head_hash": "2" * 64,
        "head_state_hash": "3" * 64,
        "head_hash_key_id": "audit-2026-10",
        "requested_by": "audit-anchor-service",
    }


def canonical(receipt: dict) -> bytes:
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
            "version": "audit-anchor-receipt-v1",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def configure(monkeypatch, store: anchor.MemoryAnchorStore) -> TestClient:
    monkeypatch.setenv("AUDIT_ANCHOR_TOKEN", TOKEN)
    monkeypatch.setenv(
        "AUDIT_ANCHOR_RECEIPT_KEYS_JSON",
        json.dumps({KEY_ID: KEY}),
    )
    monkeypatch.setenv("AUDIT_ANCHOR_RECEIPT_ACTIVE_KID", KEY_ID)
    monkeypatch.setenv("AUDIT_ANCHOR_BUCKET", "test-anchor-bucket")
    monkeypatch.setattr(anchor, "_store", lambda: store)
    return TestClient(anchor.app)


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_health_does_not_require_anchor_credential(monkeypatch) -> None:
    client = configure(monkeypatch, anchor.MemoryAnchorStore())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_anchor_returns_app_compatible_signed_receipt(
    monkeypatch,
) -> None:
    store = anchor.MemoryAnchorStore()
    client = configure(monkeypatch, store)
    body = payload()

    response = client.post(
        "/v1/anchors",
        headers={
            **auth(),
            "Idempotency-Key": body["anchor_id"],
        },
        json=body,
    )

    assert response.status_code == 201
    receipt = response.json()
    assert receipt["namespace"] == body["namespace"]
    assert receipt["anchor_id"] == body["anchor_id"]
    assert receipt["head_event_id"] == body["head_event_id"]
    assert receipt["head_hash"] == body["head_hash"]
    assert receipt["head_state_hash"] == body["head_state_hash"]
    assert receipt["head_hash_key_id"] == body["head_hash_key_id"]
    assert receipt["requested_by"] == body["requested_by"]
    assert receipt["receipt_key_id"] == KEY_ID

    expected = hmac.new(
        KEY.encode("utf-8"),
        canonical(receipt),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(receipt["receipt_signature"], expected)


def test_create_is_idempotent_and_never_replaces_existing_receipt(
    monkeypatch,
) -> None:
    store = anchor.MemoryAnchorStore()
    client = configure(monkeypatch, store)
    first_body = payload()

    first = client.post(
        "/v1/anchors",
        headers={
            **auth(),
            "Idempotency-Key": first_body["anchor_id"],
        },
        json=first_body,
    )
    assert first.status_code == 201

    changed = dict(first_body)
    changed["head_hash"] = "9" * 64
    second = client.post(
        "/v1/anchors",
        headers={
            **auth(),
            "Idempotency-Key": changed["anchor_id"],
        },
        json=changed,
    )

    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(store.rows) == 1


def test_latest_returns_most_recent_committed_receipt(monkeypatch) -> None:
    store = anchor.MemoryAnchorStore()
    client = configure(monkeypatch, store)

    receipts = []
    for digit in ("4", "5"):
        body = payload("anc_" + digit * 40)
        response = client.post(
            "/v1/anchors",
            headers={
                **auth(),
                "Idempotency-Key": body["anchor_id"],
            },
            json=body,
        )
        assert response.status_code == 201
        receipts.append(response.json())

    latest = client.get(
        "/v1/anchors/latest",
        headers=auth(),
        params={"namespace": NAMESPACE},
    )
    assert latest.status_code == 200
    assert latest.json() == receipts[-1]


def test_missing_latest_returns_404(monkeypatch) -> None:
    client = configure(monkeypatch, anchor.MemoryAnchorStore())
    response = client.get(
        "/v1/anchors/latest",
        headers=auth(),
        params={"namespace": NAMESPACE},
    )
    assert response.status_code == 404


def test_anchor_endpoints_require_bearer_token(monkeypatch) -> None:
    client = configure(monkeypatch, anchor.MemoryAnchorStore())
    body = payload()
    response = client.post(
        "/v1/anchors",
        headers={"Idempotency-Key": body["anchor_id"]},
        json=body,
    )
    assert response.status_code == 401


def test_idempotency_key_must_equal_anchor_id(monkeypatch) -> None:
    client = configure(monkeypatch, anchor.MemoryAnchorStore())
    body = payload()
    response = client.post(
        "/v1/anchors",
        headers={
            **auth(),
            "Idempotency-Key": "anc_" + "f" * 40,
        },
        json=body,
    )
    assert response.status_code == 400
