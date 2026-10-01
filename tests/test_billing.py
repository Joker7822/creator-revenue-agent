from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def create_published_job() -> dict:
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

    policy = client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "creator_age": job["creator_age"],
            "age_verified": job["age_verified"],
            "consent_verified": job["consent_verified"],
            "depicts_real_person": job["depicts_real_person"],
            "real_person_consent_verified": (
                job["real_person_consent_verified"]
            ),
            "asset_ref": None,
        },
    )
    assert policy.status_code == 200
    assert policy.json()["allowed"] is True

    approval = client.post(
        "/v1/approvals",
        headers=auth(),
        json={"job_id": job["job_id"], "required": True},
    )
    assert approval.status_code == 200

    approved = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=auth(),
        json={"reviewer": "reviewer-1"},
    )
    assert approved.status_code == 200

    publication = client.post(
        "/v1/publish",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "destination": "internal-storefront",
            "publisher": "agent-1",
        },
    )
    assert publication.status_code == 200
    return {
        "job": job,
        "publication": publication.json(),
    }


def create_product(publication_id: str, currency: str = "JPY") -> dict:
    response = client.post(
        "/v1/products",
        headers=auth(),
        json={
            "publication_id": publication_id,
            "name": "Premium release",
            "currency": currency,
            "price_minor_units": 1500,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_product_requires_publication() -> None:
    response = client.post(
        "/v1/products",
        headers=auth(),
        json={
            "publication_id": "pub_missing",
            "name": "Premium release",
            "currency": "JPY",
            "price_minor_units": 1500,
        },
    )
    assert response.status_code == 409


def test_create_product_for_publication() -> None:
    state = create_published_job()
    product = create_product(
        state["publication"]["publication_id"]
    )
    assert product["product_id"].startswith("prod_")
    assert product["currency"] == "JPY"
    assert product["price_minor_units"] == 1500


def test_transaction_is_idempotent() -> None:
    state = create_published_job()
    product = create_product(
        state["publication"]["publication_id"]
    )
    payload = {
        "transaction_id": "tx_test_001",
        "product_id": product["product_id"],
        "kind": "sale",
        "amount_minor_units": 1500,
        "currency": "JPY",
    }

    first = client.post(
        "/v1/transactions",
        headers=auth(),
        json=payload,
    )
    second = client.post(
        "/v1/transactions",
        headers=auth(),
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_transaction_idempotency_conflict() -> None:
    state = create_published_job()
    product = create_product(
        state["publication"]["publication_id"]
    )
    first = {
        "transaction_id": "tx_conflict",
        "product_id": product["product_id"],
        "kind": "sale",
        "amount_minor_units": 1500,
        "currency": "JPY",
    }
    second = {**first, "amount_minor_units": 2000}

    assert client.post(
        "/v1/transactions",
        headers=auth(),
        json=first,
    ).status_code == 200

    response = client.post(
        "/v1/transactions",
        headers=auth(),
        json=second,
    )
    assert response.status_code == 409


def test_transaction_currency_must_match_product() -> None:
    state = create_published_job()
    product = create_product(
        state["publication"]["publication_id"],
        currency="JPY",
    )
    response = client.post(
        "/v1/transactions",
        headers=auth(),
        json={
            "transaction_id": "tx_currency",
            "product_id": product["product_id"],
            "kind": "sale",
            "amount_minor_units": 1500,
            "currency": "USD",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "currency mismatch"


def test_revenue_is_grouped_by_currency() -> None:
    jpy_state = create_published_job()
    jpy = create_product(
        jpy_state["publication"]["publication_id"],
        currency="JPY",
    )
    usd_state = create_published_job()
    usd = create_product(
        usd_state["publication"]["publication_id"],
        currency="USD",
    )

    transactions = [
        {
            "transaction_id": "tx_jpy_sale_1",
            "product_id": jpy["product_id"],
            "kind": "sale",
            "amount_minor_units": 1500,
            "currency": "JPY",
        },
        {
            "transaction_id": "tx_jpy_sale_2",
            "product_id": jpy["product_id"],
            "kind": "sale",
            "amount_minor_units": 1500,
            "currency": "JPY",
        },
        {
            "transaction_id": "tx_jpy_refund",
            "product_id": jpy["product_id"],
            "kind": "refund",
            "amount_minor_units": 500,
            "currency": "JPY",
        },
        {
            "transaction_id": "tx_usd_sale",
            "product_id": usd["product_id"],
            "kind": "sale",
            "amount_minor_units": 2000,
            "currency": "USD",
        },
    ]

    for payload in transactions:
        response = client.post(
            "/v1/transactions",
            headers=auth(),
            json=payload,
        )
        assert response.status_code == 200

    response = client.get(
        "/v1/revenue",
        headers=auth(),
    )
    assert response.status_code == 200

    by_currency = {
        row["currency"]: row
        for row in response.json()["currencies"]
    }

    assert by_currency["JPY"] == {
        "currency": "JPY",
        "sales_count": 2,
        "refund_count": 1,
        "sales_minor_units": 3000,
        "refunds_minor_units": 500,
        "net_revenue_minor_units": 2500,
    }
    assert by_currency["USD"]["net_revenue_minor_units"] == 2000


def test_billing_writes_audit_events() -> None:
    state = create_published_job()
    product = create_product(
        state["publication"]["publication_id"]
    )
    client.post(
        "/v1/transactions",
        headers=auth(),
        json={
            "transaction_id": "tx_audit",
            "product_id": product["product_id"],
            "kind": "sale",
            "amount_minor_units": 1500,
            "currency": "JPY",
        },
    )

    response = client.get(
        f"/v1/audit/{state['job']['job_id']}",
        headers=auth(),
    )
    events = [row["event_type"] for row in response.json()]
    assert "product_created" in events
    assert "transaction_recorded" in events
