import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)
SECRET = "provider-secret-0000000000000000000001"


def headers(
    *,
    event_id: str,
    body: bytes,
    timestamp: int | None = None,
    secret: str = SECRET,
) -> dict[str, str]:
    timestamp = timestamp or int(time.time())
    canonical = (
        f"provider-a.{timestamp}.{event_id}.".encode("utf-8")
        + body
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Verification-Provider": "provider-a",
        "X-Verification-Event-Id": event_id,
        "X-Verification-Timestamp": str(timestamp),
        "X-Verification-Signature": f"v1={signature}",
        "Content-Type": "application/json",
    }


def body(payload: dict) -> bytes:
    return json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def verified_payload() -> dict:
    return {
        "event_type": "verification.verified",
        "provider_record_ref": "provider-record-1",
        "subject_ref": "creator-webhook-1",
        "kind": "age",
        "age_years": 24,
    }


def test_valid_webhook_creates_verification() -> None:
    raw = body(verified_payload())
    response = client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=headers(
            event_id="evt-valid-1",
            body=raw,
        ),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["duplicate"] is False
    assert data["provider"] == "provider-a"
    assert data["verification"]["status"] == "active"
    assert data["verification"]["age_years"] == 24
    assert data["verification"]["created_by"] == (
        "webhook:provider-a"
    )


def test_duplicate_event_returns_same_result() -> None:
    raw = body(verified_payload())
    first = client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=headers(
            event_id="evt-duplicate-1",
            body=raw,
        ),
    )
    second = client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=headers(
            event_id="evt-duplicate-1",
            body=raw,
        ),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["verification"]["verification_id"] == (
        second.json()["verification"]["verification_id"]
    )
    assert second.json()["duplicate"] is True


def test_event_id_payload_conflict_is_rejected() -> None:
    raw = body(verified_payload())
    event_id = "evt-conflict-1"
    first = client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=headers(event_id=event_id, body=raw),
    )
    assert first.status_code == 200

    changed = verified_payload()
    changed["age_years"] = 25
    changed_raw = body(changed)
    second = client.post(
        "/v1/webhooks/verifications",
        content=changed_raw,
        headers=headers(
            event_id=event_id,
            body=changed_raw,
        ),
    )
    assert second.status_code == 409
    assert second.json()["detail"] == (
        "webhook event id payload conflict"
    )


def test_invalid_signature_is_rejected() -> None:
    raw = body(verified_payload())
    response = client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=headers(
            event_id="evt-bad-signature-1",
            body=raw,
            secret="wrong-secret-000000000000000000000000",
        ),
    )
    assert response.status_code == 401


def test_stale_timestamp_is_rejected() -> None:
    raw = body(verified_payload())
    response = client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=headers(
            event_id="evt-stale-1",
            body=raw,
            timestamp=int(time.time()) - 1000,
        ),
    )
    assert response.status_code == 401
    assert response.json()["detail"] == (
        "webhook timestamp outside replay window"
    )


def test_revoke_webhook_revokes_existing_record() -> None:
    verified = verified_payload()
    verified["provider_record_ref"] = "provider-record-revoke"
    raw = body(verified)
    created = client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=headers(
            event_id="evt-create-revoke",
            body=raw,
        ),
    )
    assert created.status_code == 200

    revoke = {
        "event_type": "verification.revoked",
        "provider_record_ref": "provider-record-revoke",
        "subject_ref": "creator-webhook-1",
        "kind": "age",
        "reason": "provider withdrew verification",
    }
    revoke_raw = body(revoke)
    response = client.post(
        "/v1/webhooks/verifications",
        content=revoke_raw,
        headers=headers(
            event_id="evt-revoke-1",
            body=revoke_raw,
        ),
    )
    assert response.status_code == 200
    assert response.json()["verification"]["status"] == (
        "revoked"
    )
    assert response.json()["verification"]["revoked_by"] == (
        "webhook:provider-a"
    )


def test_unknown_provider_is_rejected() -> None:
    raw = body(verified_payload())
    signed = headers(
        event_id="evt-provider-1",
        body=raw,
    )
    signed["X-Verification-Provider"] = "unknown-provider"
    response = client.post(
        "/v1/webhooks/verifications",
        content=raw,
        headers=signed,
    )
    assert response.status_code == 401
