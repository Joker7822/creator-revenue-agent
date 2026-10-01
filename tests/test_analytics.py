from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def setup_publication(currency: str = "JPY") -> dict:
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
            "real_person_consent_verified": False,
        },
    ).json()

    client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "creator_age": 21,
            "age_verified": True,
            "consent_verified": True,
            "depicts_real_person": False,
            "real_person_consent_verified": False,
            "asset_ref": None,
        },
    )
    client.post(
        "/v1/approvals",
        headers=auth(),
        json={"job_id": job["job_id"], "required": True},
    )
    client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=auth(),
        json={"reviewer": "reviewer-analytics"},
    )
    publication = client.post(
        "/v1/publish",
        headers=auth(),
        json={"job_id": job["job_id"]},
    ).json()
    product = client.post(
        "/v1/products",
        headers=auth(),
        json={
            "publication_id": publication["publication_id"],
            "name": "Premium release",
            "currency": currency,
            "price_minor_units": 1500,
        },
    ).json()

    return {
        "job": job,
        "publication": publication,
        "product": product,
    }


def event(
    event_id: str,
    publication_id: str,
    event_type: str,
) -> None:
    response = client.post(
        "/v1/events",
        headers=auth(),
        json={
            "event_id": event_id,
            "publication_id": publication_id,
            "event_type": event_type,
            "metadata": {"source": "test"},
        },
    )
    assert response.status_code == 200


def test_event_requires_published_publication() -> None:
    response = client.post(
        "/v1/events",
        headers=auth(),
        json={
            "event_id": "evt_missing",
            "publication_id": "pub_missing",
            "event_type": "impression",
        },
    )
    assert response.status_code == 409


def test_event_is_idempotent() -> None:
    state = setup_publication()
    payload = {
        "event_id": "evt_same",
        "publication_id": state["publication"]["publication_id"],
        "event_type": "click",
        "metadata": {"source": "feed"},
    }
    first = client.post("/v1/events", headers=auth(), json=payload)
    second = client.post("/v1/events", headers=auth(), json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_event_idempotency_conflict() -> None:
    state = setup_publication()
    publication_id = state["publication"]["publication_id"]

    first = client.post(
        "/v1/events",
        headers=auth(),
        json={
            "event_id": "evt_conflict",
            "publication_id": publication_id,
            "event_type": "impression",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/v1/events",
        headers=auth(),
        json={
            "event_id": "evt_conflict",
            "publication_id": publication_id,
            "event_type": "click",
        },
    )
    assert second.status_code == 409


def test_metrics_combines_funnel_and_billing() -> None:
    state = setup_publication()
    publication_id = state["publication"]["publication_id"]
    product_id = state["product"]["product_id"]

    for i in range(10):
        event(f"imp_{i}", publication_id, "impression")
    for i in range(4):
        event(f"click_{i}", publication_id, "click")

    for i in range(2):
        response = client.post(
            "/v1/transactions",
            headers=auth(),
            json={
                "transaction_id": f"sale_{i}",
                "product_id": product_id,
                "kind": "sale",
                "amount_minor_units": 1500,
                "currency": "JPY",
            },
        )
        assert response.status_code == 200

    response = client.post(
        "/v1/transactions",
        headers=auth(),
        json={
            "transaction_id": "refund_1",
            "product_id": product_id,
            "kind": "refund",
            "amount_minor_units": 500,
            "currency": "JPY",
        },
    )
    assert response.status_code == 200

    metrics = client.get(
        "/v1/metrics",
        headers=auth(),
        params={
            "window": "7d",
            "publication_id": publication_id,
        },
    )
    assert metrics.status_code == 200
    data = metrics.json()

    assert data["impressions"] == 10
    assert data["clicks"] == 4
    assert data["purchases"] == 2
    assert data["refunds"] == 1
    assert data["ctr"] == 0.4
    assert data["cvr"] == 0.5
    assert data["currencies"] == [
        {
            "currency": "JPY",
            "sales_count": 2,
            "refund_count": 1,
            "sales_minor_units": 3000,
            "refunds_minor_units": 500,
            "net_revenue_minor_units": 2500,
        }
    ]


def test_metrics_do_not_mix_publications() -> None:
    first = setup_publication()
    second = setup_publication()

    event(
        "evt_first",
        first["publication"]["publication_id"],
        "impression",
    )
    event(
        "evt_second",
        second["publication"]["publication_id"],
        "click",
    )

    response = client.get(
        "/v1/metrics",
        headers=auth(),
        params={
            "window": "7d",
            "publication_id": first["publication"]["publication_id"],
        },
    )
    data = response.json()
    assert data["impressions"] == 1
    assert data["clicks"] == 0


def test_metrics_reject_invalid_window() -> None:
    response = client.get(
        "/v1/metrics",
        headers=auth(),
        params={"window": "forever"},
    )
    assert response.status_code == 400
