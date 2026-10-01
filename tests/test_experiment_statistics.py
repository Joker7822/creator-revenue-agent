from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def setup_running_experiment() -> dict:
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
    approval = client.post(
        "/v1/approvals",
        headers=auth(),
        json={"job_id": job["job_id"], "required": False},
    )
    assert approval.status_code == 200
    assert approval.json()["status"] == "pending_review"

    approved = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=auth(),
        json={"reviewer": "test-reviewer"},
    )
    assert approved.status_code == 200

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
    proposal = client.post(
        f"/v1/optimizer/proposals/{proposal['proposal_id']}/approve",
        headers=auth(),
        json={"reviewer": "business-owner"},
    ).json()
    timing_index = next(
        i
        for i, row in enumerate(proposal["recommendations"])
        if row["type"] == "timing_test"
    )
    experiment = client.post(
        "/v1/experiments",
        headers=auth(),
        json={
            "proposal_id": proposal["proposal_id"],
            "recommendation_index": timing_index,
            "owner": "statistics-owner",
        },
    ).json()
    experiment = client.post(
        f"/v1/experiments/{experiment['experiment_id']}/start",
        headers=auth(),
        json={"actor": "statistics-owner"},
    ).json()
    return {
        "job": job,
        "product": product,
        "experiment": experiment,
    }


def assign(experiment_id: str, subject_key: str) -> dict:
    response = client.post(
        f"/v1/experiments/{experiment_id}/assignments",
        headers=auth(),
        json={"subject_key": subject_key},
    )
    assert response.status_code == 200
    return response.json()


def both_arms(experiment_id: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for i in range(500):
        assignment = assign(experiment_id, f"stat-subject-{i}")
        found.setdefault(assignment["arm"], assignment)
        if set(found) == {"control", "variant"}:
            return found
    raise AssertionError("could not find both arms")


def seed_ready_data(
    experiment_id: str,
    product_id: str,
) -> None:
    arms = both_arms(experiment_id)
    for arm, assignment in arms.items():
        client.post(
            f"/v1/experiments/{experiment_id}/events",
            headers=auth(),
            json={
                "event_id": f"stat_{arm}_imp",
                "assignment_id": assignment["assignment_id"],
                "event_type": "impression",
            },
        )
        client.post(
            f"/v1/experiments/{experiment_id}/events",
            headers=auth(),
            json={
                "event_id": f"stat_{arm}_click",
                "assignment_id": assignment["assignment_id"],
                "event_type": "click",
            },
        )
        tx_id = f"stat_tx_{arm}"
        client.post(
            "/v1/transactions",
            headers=auth(),
            json={
                "transaction_id": tx_id,
                "product_id": product_id,
                "kind": "sale",
                "amount_minor_units": 1500,
                "currency": "JPY",
            },
        )
        client.post(
            f"/v1/experiments/{experiment_id}/transactions",
            headers=auth(),
            json={
                "transaction_id": tx_id,
                "assignment_id": assignment["assignment_id"],
            },
        )


def test_statistics_exposes_95_percent_intervals() -> None:
    state = setup_running_experiment()
    experiment_id = state["experiment"]["experiment_id"]
    seed_ready_data(experiment_id, state["product"]["product_id"])

    response = client.get(
        f"/v1/experiments/{experiment_id}/statistics",
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()

    assert data["confidence_level"] == 0.95
    assert data["alpha"] == 0.05
    assert data["control"]["ctr"]["ci_lower"] is not None
    assert data["control"]["ctr"]["ci_upper"] is not None
    assert data["tests"]["ctr_two_sided_p_value"] is not None
    assert data["winner"] is None
    assert data["decision"] == "manual_review_required"


def test_completion_is_blocked_before_readiness() -> None:
    state = setup_running_experiment()
    experiment_id = state["experiment"]["experiment_id"]

    response = client.post(
        f"/v1/experiments/{experiment_id}/complete",
        headers=auth(),
        json={
            "actor": "statistics-owner",
            "outcome": {"note": "too early"},
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["message"] == (
        "experiment not ready for completion"
    )


def test_ready_completion_and_review_are_separate(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EXPERIMENT_MIN_RUNTIME_HOURS", "0")
    monkeypatch.setenv(
        "EXPERIMENT_MIN_ASSIGNMENTS_PER_ARM",
        "1",
    )
    monkeypatch.setenv(
        "EXPERIMENT_MIN_IMPRESSIONS_PER_ARM",
        "1",
    )
    monkeypatch.setenv(
        "EXPERIMENT_MIN_CLICKS_PER_ARM",
        "1",
    )

    state = setup_running_experiment()
    experiment_id = state["experiment"]["experiment_id"]
    seed_ready_data(experiment_id, state["product"]["product_id"])

    statistics = client.get(
        f"/v1/experiments/{experiment_id}/statistics",
        headers=auth(),
    ).json()
    assert statistics["gates"]["all_passed"] is True

    completed = client.post(
        f"/v1/experiments/{experiment_id}/complete",
        headers=auth(),
        json={
            "actor": "statistics-owner",
            "outcome": {"note": "measurement complete"},
        },
    )
    assert completed.status_code == 200

    review = client.post(
        f"/v1/experiments/{experiment_id}/reviews",
        headers=auth(),
        json={
            "decision": "inconclusive",
            "reviewer": "business-owner",
            "reason": "manual decision after review",
        },
    )
    assert review.status_code == 200
    assert review.json()["decision"] == "inconclusive"
    assert review.json()["statistics_snapshot"]["winner"] is None

    product = client.get(
        f"/v1/products/{state['product']['product_id']}",
        headers=auth(),
    ).json()
    assert product["price_minor_units"] == 1500


def test_review_requires_completed_experiment() -> None:
    state = setup_running_experiment()
    response = client.post(
        (
            f"/v1/experiments/"
            f"{state['experiment']['experiment_id']}/reviews"
        ),
        headers=auth(),
        json={
            "decision": "inconclusive",
            "reviewer": "business-owner",
        },
    )
    assert response.status_code == 409
