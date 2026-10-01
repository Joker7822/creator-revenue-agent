from fastapi.testclient import TestClient

from api_server.main import app
from api_server.observability import operational_metrics


client = TestClient(app)


def auth(token: str = "test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_product() -> dict:
    job = client.post(
        "/v1/content/generate",
        headers=auth(),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "creator_age": 21,
            "age_verified": True,
            "consent_verified": True,
            "depicts_real_person": False,
        },
    ).json()

    assert client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={"job_id": job["job_id"]},
    ).status_code == 200
    assert client.post(
        "/v1/approvals",
        headers=auth(),
        json={"job_id": job["job_id"], "required": True},
    ).status_code == 200
    assert client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=auth(),
        json={"reviewer": "ignored"},
    ).status_code == 200
    publication = client.post(
        "/v1/publish",
        headers=auth(),
        json={"job_id": job["job_id"]},
    ).json()
    return client.post(
        "/v1/products",
        headers=auth(),
        json={
            "publication_id": publication["publication_id"],
            "name": "Rate-limited product",
            "currency": "JPY",
            "price_minor_units": 1500,
        },
    ).json()


def test_billing_rate_limit_rejects_excess_requests(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "BILLING_RATE_LIMIT_PER_MINUTE",
        "1",
    )
    product = create_product()

    first = client.post(
        "/v1/transactions",
        headers=auth("billing-token"),
        json={
            "transaction_id": "rate_sale_1",
            "product_id": product["product_id"],
            "kind": "sale",
            "amount_minor_units": 1500,
            "currency": "JPY",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/transactions",
        headers=auth("billing-token"),
        json={
            "transaction_id": "rate_sale_2",
            "product_id": product["product_id"],
            "kind": "sale",
            "amount_minor_units": 1500,
            "currency": "JPY",
        },
    )
    assert second.status_code == 429
    assert second.json()["detail"] == "rate limit exceeded"
    assert int(second.headers["Retry-After"]) >= 1

    snapshot = operational_metrics.snapshot()
    assert snapshot["incident_signals"]["rate_limit_rejections"] == 1


def test_request_body_limit_rejects_actual_body_bytes(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "MAX_REQUEST_BODY_BYTES",
        "64",
    )

    response = client.post(
        "/v1/content/generate",
        headers=auth(),
        content=b"{" + b"x" * 200 + b"}",
    )
    assert response.status_code == 413
    assert response.json()["error_code"] == (
        "request_body_too_large"
    )

    snapshot = operational_metrics.snapshot()
    assert (
        snapshot["incident_signals"][
            "oversized_request_rejections"
        ]
        == 1
    )


def test_normal_json_body_still_reaches_fastapi(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "MAX_REQUEST_BODY_BYTES",
        "4096",
    )

    response = client.post(
        "/v1/content/generate",
        headers=auth(),
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
