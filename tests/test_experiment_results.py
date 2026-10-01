from fastapi.testclient import TestClient

from api_server.db import ExperimentAssignmentRecord, SessionLocal
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
    client.post(
        "/v1/approvals",
        headers=auth(),
        json={"job_id": job["job_id"], "required": False},
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
            "owner": "experiment-owner",
        },
    ).json()
    experiment = client.post(
        f"/v1/experiments/{experiment['experiment_id']}/start",
        headers=auth(),
        json={"actor": "experiment-owner"},
    ).json()
    return {
        "job": job,
        "publication": publication,
        "product": product,
        "proposal": proposal,
        "experiment": experiment,
    }


def assign(
    experiment_id: str,
    subject_key: str,
) -> dict:
    response = client.post(
        f"/v1/experiments/{experiment_id}/assignments",
        headers=auth(),
        json={"subject_key": subject_key},
    )
    assert response.status_code == 200
    return response.json()


def find_both_arms(experiment_id: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for i in range(500):
        assignment = assign(
            experiment_id,
            f"subject-{i}",
        )
        found.setdefault(assignment["arm"], assignment)
        if set(found) == {"control", "variant"}:
            return found
    raise AssertionError("could not find both experiment arms")


def test_assignment_requires_running_experiment() -> None:
    state = setup_running_experiment()
    client.post(
        f"/v1/experiments/{state['experiment']['experiment_id']}/cancel",
        headers=auth(),
        json={
            "actor": "experiment-owner",
            "reason": "stop",
        },
    )
    response = client.post(
        f"/v1/experiments/{state['experiment']['experiment_id']}/assignments",
        headers=auth(),
        json={"subject_key": "late-subject"},
    )
    assert response.status_code == 409


def test_assignment_is_stable_and_stores_only_hash() -> None:
    state = setup_running_experiment()
    experiment_id = state["experiment"]["experiment_id"]

    first = assign(experiment_id, "user@example.test")
    second = assign(experiment_id, "user@example.test")

    assert first == second

    with SessionLocal() as session:
        record = session.get(
            ExperimentAssignmentRecord,
            first["assignment_id"],
        )
        assert record is not None
        assert record.subject_hash != "user@example.test"
        assert len(record.subject_hash) == 64


def test_experiment_event_is_idempotent() -> None:
    state = setup_running_experiment()
    experiment_id = state["experiment"]["experiment_id"]
    assignment = assign(experiment_id, "event-subject")

    payload = {
        "event_id": "exp_evt_1",
        "assignment_id": assignment["assignment_id"],
        "event_type": "impression",
    }
    first = client.post(
        f"/v1/experiments/{experiment_id}/events",
        headers=auth(),
        json=payload,
    )
    second = client.post(
        f"/v1/experiments/{experiment_id}/events",
        headers=auth(),
        json=payload,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_results_join_events_and_billing_without_winner() -> None:
    state = setup_running_experiment()
    experiment_id = state["experiment"]["experiment_id"]
    product_id = state["product"]["product_id"]
    arms = find_both_arms(experiment_id)

    for arm, assignment in arms.items():
        for i in range(2):
            response = client.post(
                f"/v1/experiments/{experiment_id}/events",
                headers=auth(),
                json={
                    "event_id": f"{arm}_imp_{i}",
                    "assignment_id": assignment["assignment_id"],
                    "event_type": "impression",
                },
            )
            assert response.status_code == 200

        response = client.post(
            f"/v1/experiments/{experiment_id}/events",
            headers=auth(),
            json={
                "event_id": f"{arm}_click_1",
                "assignment_id": assignment["assignment_id"],
                "event_type": "click",
            },
        )
        assert response.status_code == 200

        tx_id = f"tx_{arm}_sale"
        tx = client.post(
            "/v1/transactions",
            headers=auth(),
            json={
                "transaction_id": tx_id,
                "product_id": product_id,
                "kind": "sale",
                "amount_minor_units": (
                    1500 if arm == "control" else 1800
                ),
                "currency": "JPY",
            },
        )
        assert tx.status_code == 200

        linked = client.post(
            f"/v1/experiments/{experiment_id}/transactions",
            headers=auth(),
            json={
                "transaction_id": tx_id,
                "assignment_id": assignment["assignment_id"],
            },
        )
        assert linked.status_code == 200

    response = client.get(
        f"/v1/experiments/{experiment_id}/results",
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()

    assert data["control"]["impressions"] == 2
    assert data["variant"]["impressions"] == 2
    assert data["control"]["clicks"] == 1
    assert data["variant"]["clicks"] == 1
    assert data["control"]["purchases"] == 1
    assert data["variant"]["purchases"] == 1
    assert data["control"]["ctr"] == 0.5
    assert data["variant"]["ctr"] == 0.5
    assert data["control"]["cvr"] == 1.0
    assert data["variant"]["cvr"] == 1.0
    assert data["comparison"]["winner"] is None
    assert data["comparison"]["decision"] == "manual_review_required"
    assert data["comparison"]["net_revenue_delta_by_currency"]["JPY"] in (
        300,
        -300,
    )
    assert data["evaluation_status"] == "insufficient_data"


def test_transaction_must_match_experiment_product() -> None:
    first = setup_running_experiment()
    second = setup_running_experiment()

    assignment = assign(
        first["experiment"]["experiment_id"],
        "product-check-subject",
    )
    tx = client.post(
        "/v1/transactions",
        headers=auth(),
        json={
            "transaction_id": "tx_wrong_product",
            "product_id": second["product"]["product_id"],
            "kind": "sale",
            "amount_minor_units": 1500,
            "currency": "JPY",
        },
    )
    assert tx.status_code == 200

    response = client.post(
        (
            f"/v1/experiments/"
            f"{first['experiment']['experiment_id']}/transactions"
        ),
        headers=auth(),
        json={
            "transaction_id": "tx_wrong_product",
            "assignment_id": assignment["assignment_id"],
        },
    )
    assert response.status_code == 409
