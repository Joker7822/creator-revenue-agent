from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def issue(role: str, subject: str) -> str:
    response = client.post(
        "/v1/auth/credentials",
        headers=bearer("credential-admin-token"),
        json={
            "subject": subject,
            "roles": [role],
            "ttl_seconds": 900,
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_production_identity_and_revenue_flow(
    monkeypatch,
) -> None:
    verification_token = issue(
        "verification_writer",
        "prod-verification",
    )
    reviewer_token = issue("reviewer", "prod-reviewer")
    publisher_token = issue("publisher", "prod-publisher")
    billing_token = issue(
        "billing_writer",
        "prod-billing",
    )
    reader_token = issue("reader", "prod-reader")

    monkeypatch.setenv("SERVICE_AUTH_MODE", "jwt")
    monkeypatch.setenv(
        "REQUIRE_TRUSTED_VERIFICATION",
        "true",
    )

    creator_ref = "creator-prod-e2e"
    age = client.post(
        "/v1/verifications",
        headers=bearer(verification_token),
        json={
            "subject_ref": creator_ref,
            "kind": "age",
            "source": "provider-e2e",
            "source_record_ref": "age-e2e",
            "age_years": 24,
        },
    )
    consent = client.post(
        "/v1/verifications",
        headers=bearer(verification_token),
        json={
            "subject_ref": creator_ref,
            "kind": "creator_consent",
            "source": "provider-e2e",
            "source_record_ref": "consent-e2e",
        },
    )
    assert age.status_code == 200
    assert consent.status_code == 200

    content = client.post(
        "/v1/content/generate",
        headers=bearer(reader_token),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "creator_ref": creator_ref,
            "age_verification_id": (
                age.json()["verification_id"]
            ),
            "consent_verification_id": (
                consent.json()["verification_id"]
            ),
            "depicts_real_person": False,
        },
    )
    assert content.status_code == 200
    job = content.json()

    policy = client.post(
        "/v1/policy/evaluate",
        headers=bearer(reader_token),
        json={"job_id": job["job_id"]},
    )
    assert policy.status_code == 200
    assert policy.json()["allowed"] is True

    approval = client.post(
        "/v1/approvals",
        headers=bearer(reader_token),
        json={
            "job_id": job["job_id"],
            "required": True,
        },
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "pending_review"

    approved = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=bearer(reviewer_token),
        json={
            "reviewer": "spoofed",
            "reason": "production e2e",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["reviewer"] == "prod-reviewer"

    publication = client.post(
        "/v1/publish",
        headers=bearer(publisher_token),
        json={
            "job_id": job["job_id"],
            "destination": "internal-storefront",
            "publisher": "spoofed",
        },
    )
    assert publication.status_code == 200
    assert publication.json()["publisher"] == "prod-publisher"

    product = client.post(
        "/v1/products",
        headers=bearer(billing_token),
        json={
            "publication_id": publication.json()[
                "publication_id"
            ],
            "name": "Production E2E",
            "currency": "JPY",
            "price_minor_units": 1500,
        },
    )
    assert product.status_code == 200

    sale = client.post(
        "/v1/transactions",
        headers=bearer(billing_token),
        json={
            "transaction_id": "prod-e2e-sale",
            "product_id": product.json()["product_id"],
            "kind": "sale",
            "amount_minor_units": 1500,
            "currency": "JPY",
        },
    )
    assert sale.status_code == 200

    refund = client.post(
        "/v1/transactions",
        headers=bearer(billing_token),
        json={
            "transaction_id": "prod-e2e-refund",
            "product_id": product.json()["product_id"],
            "kind": "refund",
            "original_sale_id": "prod-e2e-sale",
            "amount_minor_units": 500,
            "currency": "JPY",
        },
    )
    assert refund.status_code == 200

    revenue = client.get(
        "/v1/revenue",
        headers=bearer(reader_token),
    )
    assert revenue.status_code == 200
    jpy = next(
        row
        for row in revenue.json()["currencies"]
        if row["currency"] == "JPY"
    )
    assert jpy["sales_minor_units"] == 1500
    assert jpy["refunds_minor_units"] == 500
    assert jpy["net_revenue_minor_units"] == 1000

    audit = client.get(
        f"/v1/audit/{job['job_id']}",
        headers=bearer(reader_token),
    )
    assert audit.status_code == 200
    events = [row["event_type"] for row in audit.json()]
    assert "job_created" in events
    assert "approval_approved" in events
    assert "publication_published" in events
    assert "product_created" in events
    assert events.count("transaction_recorded") == 2

    integrity = client.get(
        "/v1/audit/integrity",
        headers=bearer(reader_token),
    )
    assert integrity.status_code == 200
    assert integrity.json()["valid"] is True
