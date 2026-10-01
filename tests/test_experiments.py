from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def setup_approved_proposal() -> dict:
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
        json={"reviewer": "experiment-reviewer"},
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
            "currency": "JPY",
            "price_minor_units": 1500,
        },
    ).json()

    proposal = client.post(
        "/v1/optimizer/proposals",
        headers=auth(),
        json={
            "publication_id": publication["publication_id"],
            "window": "7d",
        },
    ).json()

    approved = client.post(
        f"/v1/optimizer/proposals/{proposal['proposal_id']}/approve",
        headers=auth(),
        json={
            "reviewer": "business-owner",
            "reason": "approve experiment plan",
        },
    )
    assert approved.status_code == 200

    return {
        "job": job,
        "publication": publication,
        "product": product,
        "proposal": approved.json(),
    }


def test_experiment_requires_approved_proposal() -> None:
    state = setup_approved_proposal()
    pending = client.post(
        "/v1/optimizer/proposals",
        headers=auth(),
        json={
            "publication_id": state["publication"]["publication_id"],
            "window": "7d",
        },
    ).json()

    response = client.post(
        "/v1/experiments",
        headers=auth(),
        json={
            "proposal_id": pending["proposal_id"],
            "recommendation_index": 0,
            "owner": "owner-1",
        },
    )
    assert response.status_code == 409


def test_data_collection_recommendation_is_not_experimentable() -> None:
    state = setup_approved_proposal()

    response = client.post(
        "/v1/experiments",
        headers=auth(),
        json={
            "proposal_id": state["proposal"]["proposal_id"],
            "recommendation_index": 0,
            "owner": "owner-1",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "recommendation is not experimentable"
    )


def test_timing_experiment_is_draft_and_idempotent() -> None:
    state = setup_approved_proposal()
    recommendations = state["proposal"]["recommendations"]
    index = next(
        i
        for i, row in enumerate(recommendations)
        if row["type"] == "timing_test"
    )
    payload = {
        "proposal_id": state["proposal"]["proposal_id"],
        "recommendation_index": index,
        "owner": "owner-1",
    }

    first = client.post(
        "/v1/experiments",
        headers=auth(),
        json=payload,
    )
    second = client.post(
        "/v1/experiments",
        headers=auth(),
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["experiment_id"] == second.json()["experiment_id"]
    assert first.json()["status"] == "draft"
    assert first.json()["plan"]["automatic_application"] is False


def test_start_does_not_mutate_product() -> None:
    state = setup_approved_proposal()
    recommendations = state["proposal"]["recommendations"]
    index = next(
        i
        for i, row in enumerate(recommendations)
        if row["type"] == "timing_test"
    )
    experiment = client.post(
        "/v1/experiments",
        headers=auth(),
        json={
            "proposal_id": state["proposal"]["proposal_id"],
            "recommendation_index": index,
            "owner": "owner-1",
        },
    ).json()

    started = client.post(
        f"/v1/experiments/{experiment['experiment_id']}/start",
        headers=auth(),
        json={"actor": "owner-1"},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "running"

    product = client.get(
        f"/v1/products/{state['product']['product_id']}",
        headers=auth(),
    ).json()
    assert product["price_minor_units"] == 1500


def test_complete_experiment_records_outcome_and_audit(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EXPERIMENT_MIN_RUNTIME_HOURS", "0")
    monkeypatch.setenv(
        "EXPERIMENT_MIN_ASSIGNMENTS_PER_ARM",
        "0",
    )
    monkeypatch.setenv(
        "EXPERIMENT_MIN_IMPRESSIONS_PER_ARM",
        "0",
    )
    monkeypatch.setenv(
        "EXPERIMENT_MIN_CLICKS_PER_ARM",
        "0",
    )

    state = setup_approved_proposal()
    recommendations = state["proposal"]["recommendations"]
    index = next(
        i
        for i, row in enumerate(recommendations)
        if row["type"] == "timing_test"
    )
    experiment = client.post(
        "/v1/experiments",
        headers=auth(),
        json={
            "proposal_id": state["proposal"]["proposal_id"],
            "recommendation_index": index,
            "owner": "owner-1",
        },
    ).json()

    client.post(
        f"/v1/experiments/{experiment['experiment_id']}/start",
        headers=auth(),
        json={"actor": "owner-1"},
    )
    completed = client.post(
        f"/v1/experiments/{experiment['experiment_id']}/complete",
        headers=auth(),
        json={
            "actor": "owner-1",
            "outcome": {
                "winner": "undetermined",
                "note": "manual analysis required",
            },
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["outcome"]["winner"] == "undetermined"

    audit = client.get(
        f"/v1/audit/{state['job']['job_id']}",
        headers=auth(),
    ).json()
    events = [row["event_type"] for row in audit]
    assert "experiment_created" in events
    assert "experiment_started" in events
    assert "experiment_completed" in events
