from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def reader() -> dict[str, str]:
    return {"Authorization": "Bearer reader-token"}


def test_reader_cannot_use_high_risk_write_surfaces() -> None:
    cases = [
        (
            "/v1/auth/credentials",
            {
                "subject": "blocked",
                "roles": ["reader"],
                "ttl_seconds": 60,
            },
        ),
        (
            "/v1/verifications",
            {
                "subject_ref": "creator-security",
                "kind": "age",
                "source": "manual",
                "source_record_ref": "blocked",
                "age_years": 25,
            },
        ),
        (
            "/v1/products",
            {
                "publication_id": "pub_blocked",
                "name": "blocked",
                "currency": "JPY",
                "price_minor_units": 1000,
            },
        ),
        (
            "/v1/transactions",
            {
                "transaction_id": "tx_blocked",
                "product_id": "prod_blocked",
                "kind": "sale",
                "amount_minor_units": 1000,
                "currency": "JPY",
            },
        ),
        (
            "/v1/change-sets/change_blocked/apply",
            {"actor": "ignored"},
        ),
        (
            "/v1/rollouts/roll_blocked/rollback",
            {
                "actor": "ignored",
                "reason": "blocked",
            },
        ),
    ]

    for path, payload in cases:
        response = client.post(
            path,
            headers=reader(),
            json=payload,
        )
        assert response.status_code == 403, (
            path,
            response.status_code,
            response.text,
        )


def test_ops_status_requires_authentication() -> None:
    response = client.get("/v1/ops/status")
    assert response.status_code == 401


def test_internal_errors_do_not_echo_sensitive_request_data(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "MAX_REQUEST_BODY_BYTES",
        "1024",
    )
    secret = "do-not-reflect-this-secret"
    response = client.post(
        "/v1/content/generate",
        headers={
            "Authorization": f"Bearer {secret}",
            "X-Request-ID": "security-error-1234",
        },
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

    assert response.status_code == 401
    assert secret not in response.text
    assert "members_only_release" not in response.text
