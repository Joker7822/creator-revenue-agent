from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def verified_job() -> dict:
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
            "real_person_consent_verified": False,
        },
    )
    assert response.status_code == 200
    job = response.json()

    policy = client.post(
        "/v1/policy/evaluate",
        headers=bearer("test-token"),
        json={"job_id": job["job_id"]},
    )
    assert policy.status_code == 200
    assert policy.json()["allowed"] is True

    approval = client.post(
        "/v1/approvals",
        headers=bearer("test-token"),
        json={"job_id": job["job_id"], "required": True},
    )
    assert approval.status_code == 200
    return job


def test_reader_cannot_approve_job() -> None:
    job = verified_job()

    response = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=bearer("reader-token"),
        json={
            "reviewer": "spoofed-reviewer",
            "reason": "should not be trusted",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "insufficient service role"
    )


def test_reviewer_identity_comes_from_token() -> None:
    job = verified_job()

    response = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=bearer("reviewer-token"),
        json={
            "reviewer": "spoofed-reviewer",
            "reason": "verified",
        },
    )
    assert response.status_code == 200
    assert response.json()["reviewer"] == "reviewer-service"

    audit = client.get(
        f"/v1/audit/{job['job_id']}",
        headers=bearer("reader-token"),
    )
    assert audit.status_code == 200
    approved = [
        row
        for row in audit.json()
        if row["event_type"] == "approval_approved"
    ]
    assert approved[-1]["actor"] == "reviewer-service"


def test_publisher_identity_comes_from_token() -> None:
    job = verified_job()
    approved = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=bearer("reviewer-token"),
        json={"reviewer": "ignored"},
    )
    assert approved.status_code == 200

    denied = client.post(
        "/v1/publish",
        headers=bearer("reader-token"),
        json={
            "job_id": job["job_id"],
            "publisher": "spoofed-publisher",
        },
    )
    assert denied.status_code == 403

    published = client.post(
        "/v1/publish",
        headers=bearer("publisher-token"),
        json={
            "job_id": job["job_id"],
            "publisher": "spoofed-publisher",
        },
    )
    assert published.status_code == 200
    assert published.json()["publisher"] == "publisher-service"


def test_invalid_service_token_is_rejected() -> None:
    response = client.get(
        "/v1/revenue",
        headers=bearer("not-configured"),
    )
    assert response.status_code == 401
