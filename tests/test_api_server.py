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


def create_and_approve(
    job: dict,
) -> None:
    response = client.post(
        "/v1/approvals",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "required": True,
        },
    )
    assert response.status_code == 200

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


def test_publish_requires_policy() -> None:
    job = create_verified_job()

    response = client.post(
        "/v1/publish",
        headers=auth(),
        json={"job_id": job["job_id"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "policy approval required"
    )


def test_publish_requires_human_approval() -> None:
    job = create_verified_job()
    approve_policy(job)

    response = client.post(
        "/v1/publish",
        headers=auth(),
        json={"job_id": job["job_id"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "human approval required"
    )


def test_publish_rejects_rejected_approval() -> None:
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
    client.post(
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

    response = client.post(
        "/v1/publish",
        headers=auth(),
        json={"job_id": job["job_id"]},
    )

    assert response.status_code == 409


def test_publish_after_approval_is_idempotent() -> None:
    job = create_verified_job()
    approve_policy(job)
    create_and_approve(job)

    payload = {
        "job_id": job["job_id"],
        "destination": "internal-storefront",
        "publisher": "agent-1",
    }

    first = client.post(
        "/v1/publish",
        headers=auth(),
        json=payload,
    )
    second = client.post(
        "/v1/publish",
        headers=auth(),
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert (
        first.json()["publication_id"]
        == second.json()["publication_id"]
    )
    assert first.json()["status"] == "published"

    fetched = client.get(
        f"/v1/publications/{job['job_id']}",
        headers=auth(),
    )
    assert fetched.status_code == 200
    assert (
        fetched.json()["publication_id"]
        == first.json()["publication_id"]
    )

    audit = client.get(
        f"/v1/audit/{job['job_id']}",
        headers=auth(),
    )
    events = [
        event["event_type"]
        for event in audit.json()
    ]
    assert events.count(
        "publication_published"
    ) == 1



def test_required_false_cannot_bypass_human_review() -> None:
    job = create_verified_job()
    approve_policy(job)

    response = client.post(
        "/v1/approvals",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "required": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["required"] is True
    assert response.json()["status"] == "pending_review"

    publish = client.post(
        "/v1/publish",
        headers=auth(),
        json={"job_id": job["job_id"]},
    )
    assert publish.status_code == 409


def test_job_policy_uses_persisted_verification_facts() -> None:
    response = client.post(
        "/v1/content/generate",
        headers=auth(),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "creator_age": 17,
            "age_verified": False,
            "consent_verified": False,
            "depicts_real_person": False,
            "real_person_consent_verified": False,
        },
    )
    assert response.status_code == 200
    job = response.json()

    policy = client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={
            "job_id": job["job_id"],
            "creator_age": 30,
            "age_verified": True,
            "consent_verified": True,
            "depicts_real_person": False,
            "real_person_consent_verified": True,
        },
    )

    assert policy.status_code == 200
    assert policy.json()["allowed"] is False
    assert "adult_age_not_verified" in policy.json()["reasons"]
    assert "age_verification_required" in policy.json()["reasons"]
    assert "creator_consent_required" in policy.json()["reasons"]
