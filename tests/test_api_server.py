from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {
        "Authorization": "Bearer test-token",
    }


def create_verified_job() -> dict:
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
            "real_person_consent_verified": False,
        },
    )
    assert response.status_code == 200
    return response.json()


def approve_policy(
    job: dict,
) -> None:
    response = client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "creator_age": job["creator_age"],
            "age_verified": job["age_verified"],
            "consent_verified": (
                job["consent_verified"]
            ),
            "depicts_real_person": (
                job["depicts_real_person"]
            ),
            "real_person_consent_verified": (
                job[
                    "real_person_consent_verified"
                ]
            ),
            "asset_ref": job["asset_ref"],
        },
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
    }


def test_auth_required() -> None:
    response = client.post(
        "/v1/policy/evaluate",
        json={},
    )
    assert response.status_code == 401


def test_generate_campaign_metadata() -> None:
    data = create_verified_job()

    assert data["job_id"].startswith("job_")
    assert data["asset_ref"] is None


def test_policy_rejects_minor() -> None:
    response = client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={
            "creator_age": 17,
            "age_verified": True,
            "consent_verified": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert (
        "adult_age_not_verified"
        in response.json()["reasons"]
    )


def test_policy_rejects_github_asset() -> None:
    response = client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={
            "creator_age": 25,
            "age_verified": True,
            "consent_verified": True,
            "asset_ref": (
                "https://github.com/example/"
                "repo/blob/main/media/x"
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert (
        "github_asset_storage_not_allowed"
        in response.json()["reasons"]
    )


def test_approval_requires_policy() -> None:
    job = create_verified_job()

    response = client.post(
        "/v1/approvals",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "required": True,
        },
    )

    assert response.status_code == 409


def test_approval_flow_and_audit() -> None:
    job = create_verified_job()
    approve_policy(job)

    response = client.post(
        "/v1/approvals",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "required": True,
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["status"]
        == "pending_review"
    )

    response = client.post(
        (
            f"/v1/approvals/"
            f"{job['job_id']}/approve"
        ),
        headers=auth(),
        json={
            "reviewer": "reviewer-1",
            "reason": "verification complete",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert (
        response.json()["reviewer"]
        == "reviewer-1"
    )

    response = client.get(
        f"/v1/audit/{job['job_id']}",
        headers=auth(),
    )

    assert response.status_code == 200
    event_types = [
        event["event_type"]
        for event in response.json()
    ]
    assert event_types == [
        "job_created",
        "policy_evaluated",
        "approval_created",
        "approval_approved",
    ]


def test_reject_flow() -> None:
    job = create_verified_job()
    approve_policy(job)

    client.post(
        "/v1/approvals",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "required": True,
        },
    )

    response = client.post(
        (
            f"/v1/approvals/"
            f"{job['job_id']}/reject"
        ),
        headers=auth(),
        json={
            "reviewer": "reviewer-2",
            "reason": "manual review failed",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
