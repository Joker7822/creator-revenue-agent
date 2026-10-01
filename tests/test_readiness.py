import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

import api_server.audit_anchor as audit_anchor
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


class WormStore:
    def __init__(
        self,
        *,
        anchored_at: datetime | None = None,
    ) -> None:
        self.latest: dict | None = None
        self.anchored_at = anchored_at

    def handler(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        if (
            request.method == "POST"
            and request.url.path == "/v1/anchors"
        ):
            payload = json.loads(request.content)
            receipt = {
                **payload,
                "receipt_id": (
                    f"receipt-{payload['anchor_id']}"
                ),
                "anchored_at": (
                    self.anchored_at
                    or datetime.now(timezone.utc)
                ).isoformat(),
                "receipt_key_id": RECEIPT_KEY_ID,
            }
            receipt["receipt_signature"] = (
                receipt_signature(receipt)
            )
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


def install(
    monkeypatch,
    store: WormStore,
) -> None:
    monkeypatch.setattr(
        audit_anchor,
        "_http_client",
        store.client,
    )


def make_anchor(
    monkeypatch,
    store: WormStore,
) -> None:
    install(monkeypatch, store)
    response = client.post(
        "/v1/audit/anchors",
        headers=bearer("audit-anchor-token"),
    )
    assert response.status_code == 200


def production_settings(monkeypatch) -> None:
    monkeypatch.setenv("SERVICE_AUTH_MODE", "jwt")
    monkeypatch.setenv(
        "REQUIRE_TRUSTED_VERIFICATION",
        "true",
    )
    monkeypatch.setenv(
        "AUDIT_ANCHOR_MAX_AGE_SECONDS",
        "300",
    )
    monkeypatch.setenv(
        "AUDIT_ANCHOR_MAX_UNANCHORED_EVENTS",
        "10",
    )


def test_production_readiness_is_ready_with_fresh_anchor(
    monkeypatch,
) -> None:
    create_job()
    store = WormStore()
    make_anchor(monkeypatch, store)
    production_settings(monkeypatch)

    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert all(row["ready"] for row in data["checks"])


def test_readiness_fails_for_stale_anchor(
    monkeypatch,
) -> None:
    create_job()
    store = WormStore(
        anchored_at=(
            datetime.now(timezone.utc)
            - timedelta(seconds=600)
        )
    )
    make_anchor(monkeypatch, store)
    production_settings(monkeypatch)

    response = client.get("/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["ready"] is False

    anchor_check = next(
        row
        for row in data["checks"]
        if row["name"] == "audit_anchor_freshness"
    )
    assert anchor_check["ready"] is False
    assert "too old" in anchor_check["detail"]


def test_readiness_fails_for_unanchored_event_gap(
    monkeypatch,
) -> None:
    job = create_job()
    store = WormStore()
    make_anchor(monkeypatch, store)
    add_policy_event(job)
    production_settings(monkeypatch)
    monkeypatch.setenv(
        "AUDIT_ANCHOR_MAX_UNANCHORED_EVENTS",
        "0",
    )

    response = client.get("/ready")
    assert response.status_code == 503
    data = response.json()
    anchor_check = next(
        row
        for row in data["checks"]
        if row["name"] == "audit_anchor_freshness"
    )
    assert anchor_check["ready"] is False
    assert "unanchored" in anchor_check["detail"]


def test_freshness_endpoint_reports_limits(
    monkeypatch,
) -> None:
    create_job()
    store = WormStore()
    make_anchor(monkeypatch, store)
    monkeypatch.setenv(
        "AUDIT_ANCHOR_MAX_AGE_SECONDS",
        "300",
    )
    monkeypatch.setenv(
        "AUDIT_ANCHOR_MAX_UNANCHORED_EVENTS",
        "10",
    )

    response = client.get(
        "/v1/audit/anchors/freshness",
        headers=bearer("test-token"),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["fresh"] is True
    assert data["max_age_seconds"] == 300
    assert data["max_unanchored_events"] == 10



def test_readiness_fails_when_row_locking_database_is_required(
    monkeypatch,
) -> None:
    create_job()
    store = WormStore()
    make_anchor(monkeypatch, store)
    production_settings(monkeypatch)
    monkeypatch.setenv(
        "PRODUCTION_REQUIRE_ROW_LOCKING_DATABASE",
        "true",
    )

    response = client.get("/ready")
    assert response.status_code == 503
    data = response.json()
    database_check = next(
        row
        for row in data["checks"]
        if row["name"] == "database_concurrency"
    )
    assert database_check["ready"] is False
    assert "dialect=sqlite" in database_check["detail"]
