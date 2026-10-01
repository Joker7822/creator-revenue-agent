from fastapi.testclient import TestClient

from api_server.db import ProductRecord, SessionLocal
from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def role_auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def setup_price_review(monkeypatch, decision: str) -> dict:
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
        json={"job_id": job["job_id"]},
    )
    client.post(
        "/v1/approvals",
        headers=auth(),
        json={"job_id": job["job_id"], "required": True},
    )
    client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=auth(),
        json={"reviewer": "content-reviewer"},
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

    publication_id = publication["publication_id"]
    for i in range(100):
        response = client.post(
            "/v1/events",
            headers=auth(),
            json={
                "event_id": f"roll_imp_{i}",
                "publication_id": publication_id,
                "event_type": "impression",
            },
        )
        assert response.status_code == 200
    for i in range(25):
        response = client.post(
            "/v1/events",
            headers=auth(),
            json={
                "event_id": f"roll_click_{i}",
                "publication_id": publication_id,
                "event_type": "click",
            },
        )
        assert response.status_code == 200

    proposal = client.post(
        "/v1/optimizer/proposals",
        headers=auth(),
        json={
            "publication_id": publication_id,
            "window": "7d",
        },
    ).json()
    price_index = next(
        i
        for i, row in enumerate(proposal["recommendations"])
        if row["type"] == "price_test"
    )
    proposal = client.post(
        f"/v1/optimizer/proposals/{proposal['proposal_id']}/approve",
        headers=auth(),
        json={"reviewer": "experiment-plan-reviewer"},
    ).json()

    experiment = client.post(
        "/v1/experiments",
        headers=auth(),
        json={
            "proposal_id": proposal["proposal_id"],
            "recommendation_index": price_index,
            "owner": "experiment-owner",
        },
    ).json()
    experiment = client.post(
        f"/v1/experiments/{experiment['experiment_id']}/start",
        headers=auth(),
        json={"actor": "experiment-owner"},
    ).json()

    found: dict[str, dict] = {}
    for i in range(500):
        assignment = client.post(
            (
                f"/v1/experiments/"
                f"{experiment['experiment_id']}/assignments"
            ),
            headers=auth(),
            json={"subject_key": f"roll-subject-{i}"},
        ).json()
        found.setdefault(assignment["arm"], assignment)
        if set(found) == {"control", "variant"}:
            break
    assert set(found) == {"control", "variant"}

    for arm, assignment in found.items():
        for event_type in ("impression", "click"):
            response = client.post(
                (
                    f"/v1/experiments/"
                    f"{experiment['experiment_id']}/events"
                ),
                headers=auth(),
                json={
                    "event_id": f"roll_{arm}_{event_type}",
                    "assignment_id": assignment["assignment_id"],
                    "event_type": event_type,
                },
            )
            assert response.status_code == 200

    completed = client.post(
        (
            f"/v1/experiments/"
            f"{experiment['experiment_id']}/complete"
        ),
        headers=auth(),
        json={
            "actor": "experiment-owner",
            "outcome": {"note": "measurement complete"},
        },
    )
    assert completed.status_code == 200

    review = client.post(
        (
            f"/v1/experiments/"
            f"{experiment['experiment_id']}/reviews"
        ),
        headers=auth(),
        json={
            "decision": decision,
            "reviewer": "result-reviewer",
            "reason": "manual experiment result review",
        },
    )
    assert review.status_code == 200

    return {
        "job": job,
        "product": product,
        "experiment": experiment,
        "review": review.json(),
    }


def create_change_set(state: dict) -> dict:
    response = client.post(
        "/v1/change-sets",
        headers=auth(),
        json={
            "review_id": state["review"]["review_id"],
            "created_by": "rollout-planner",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_change_set_requires_variant_preferred(
    monkeypatch,
) -> None:
    state = setup_price_review(
        monkeypatch,
        "inconclusive",
    )

    response = client.post(
        "/v1/change-sets",
        headers=auth(),
        json={
            "review_id": state["review"]["review_id"],
            "created_by": "rollout-planner",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "variant_preferred review required"
    )


def test_change_set_enforces_separation_of_duties(
    monkeypatch,
) -> None:
    state = setup_price_review(
        monkeypatch,
        "variant_preferred",
    )
    change_set = create_change_set(state)

    same_reviewer = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/approve"
        ),
        headers=auth(),
        json={"actor": "result-reviewer"},
    )
    assert same_reviewer.status_code == 409

    same_creator = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/approve"
        ),
        headers=auth(),
        json={"actor": "rollout-planner"},
    )
    assert same_creator.status_code == 409


def test_rollout_applies_price_once(
    monkeypatch,
) -> None:
    state = setup_price_review(
        monkeypatch,
        "variant_preferred",
    )
    change_set = create_change_set(state)

    approved = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/approve"
        ),
        headers=role_auth("release-token"),
        json={
            "actor": "spoofed-release-manager",
            "reason": "approved for controlled rollout",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    first = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/apply"
        ),
        headers=role_auth("rollout-token"),
        json={"actor": "spoofed-rollout-operator"},
    )
    second = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/apply"
        ),
        headers=role_auth("rollout-token"),
        json={"actor": "spoofed-rollout-operator"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["rollout_id"] == second.json()["rollout_id"]
    assert first.json()["before"]["price_minor_units"] == 1500
    assert first.json()["after"]["price_minor_units"] == 1350

    product = client.get(
        f"/v1/products/{state['product']['product_id']}",
        headers=auth(),
    ).json()
    assert product["price_minor_units"] == 1350

    audit = client.get(
        f"/v1/audit/{state['job']['job_id']}",
        headers=auth(),
    ).json()
    events = [row["event_type"] for row in audit]
    assert events.count("change_set_created") == 1
    assert events.count("change_set_approved") == 1
    assert events.count("rollout_applied") == 1


def test_rollout_blocks_stale_production_state(
    monkeypatch,
) -> None:
    state = setup_price_review(
        monkeypatch,
        "variant_preferred",
    )
    change_set = create_change_set(state)
    approved = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/approve"
        ),
        headers=role_auth("release-token"),
        json={"actor": "spoofed-release-manager"},
    )
    assert approved.status_code == 200

    with SessionLocal() as session:
        product = session.get(
            ProductRecord,
            state["product"]["product_id"],
        )
        assert product is not None
        product.price_minor_units = 1400
        session.commit()

    response = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/apply"
        ),
        headers=role_auth("rollout-token"),
        json={"actor": "spoofed-rollout-operator"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "production state changed since change set creation"
    )

    product = client.get(
        f"/v1/products/{state['product']['product_id']}",
        headers=auth(),
    ).json()
    assert product["price_minor_units"] == 1400



def _approved_and_applied_rollout(
    monkeypatch,
) -> tuple[dict, dict]:
    state = setup_price_review(
        monkeypatch,
        "variant_preferred",
    )
    change_set = create_change_set(state)

    approved = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/approve"
        ),
        headers=role_auth("release-token"),
        json={"actor": "spoofed-release-manager"},
    )
    assert approved.status_code == 200

    rollout = client.post(
        (
            f"/v1/change-sets/"
            f"{change_set['change_set_id']}/apply"
        ),
        headers=role_auth("rollout-token"),
        json={"actor": "spoofed-rollout-operator"},
    )
    assert rollout.status_code == 200
    return state, rollout.json()


def test_rollout_monitor_reports_state_and_metrics(
    monkeypatch,
) -> None:
    state, rollout = _approved_and_applied_rollout(
        monkeypatch,
    )
    publication_id = state["experiment"]["publication_id"]

    client.post(
        "/v1/events",
        headers=auth(),
        json={
            "event_id": "post_rollout_impression",
            "publication_id": publication_id,
            "event_type": "impression",
        },
    )
    client.post(
        "/v1/events",
        headers=auth(),
        json={
            "event_id": "post_rollout_click",
            "publication_id": publication_id,
            "event_type": "click",
        },
    )
    client.post(
        "/v1/transactions",
        headers=auth(),
        json={
            "transaction_id": "post_rollout_sale",
            "product_id": state["product"]["product_id"],
            "kind": "sale",
            "amount_minor_units": 1350,
            "currency": "JPY",
        },
    )

    response = client.get(
        (
            f"/v1/rollouts/"
            f"{rollout['rollout_id']}/monitor"
        ),
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()

    assert data["monitoring_status"] == "state_consistent"
    assert data["automatic_rollback"] is False
    assert data["current_state"]["price_minor_units"] == 1350
    assert data["impressions"] == 1
    assert data["clicks"] == 1
    assert data["purchases"] == 1
    assert data["ctr"] == 1.0
    assert data["cvr"] == 1.0
    assert data["currencies"] == [
        {
            "currency": "JPY",
            "sales_minor_units": 1350,
            "refunds_minor_units": 0,
            "net_revenue_minor_units": 1350,
        }
    ]


def test_rollback_restores_price_and_is_idempotent(
    monkeypatch,
) -> None:
    state, rollout = _approved_and_applied_rollout(
        monkeypatch,
    )
    url = (
        f"/v1/rollouts/{rollout['rollout_id']}/rollback"
    )
    payload = {
        "actor": "incident-manager",
        "reason": "manual rollback test",
    }

    first = client.post(
        url,
        headers=role_auth("incident-token"),
        json=payload,
    )
    second = client.post(
        url,
        headers=role_auth("incident-token"),
        json=payload,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["rollback_id"] == (
        second.json()["rollback_id"]
    )
    assert first.json()["before"]["price_minor_units"] == 1350
    assert first.json()["after"]["price_minor_units"] == 1500

    product = client.get(
        f"/v1/products/{state['product']['product_id']}",
        headers=auth(),
    ).json()
    assert product["price_minor_units"] == 1500

    rollout_state = client.get(
        f"/v1/rollouts/{rollout['rollout_id']}",
        headers=auth(),
    ).json()
    assert rollout_state["status"] == "rolled_back"

    monitor = client.get(
        (
            f"/v1/rollouts/"
            f"{rollout['rollout_id']}/monitor"
        ),
        headers=auth(),
    ).json()
    assert monitor["monitoring_status"] == "state_consistent"
    assert monitor["expected_state"]["price_minor_units"] == 1500
    assert monitor["metrics_window_end"] is not None

    audit = client.get(
        f"/v1/audit/{state['job']['job_id']}",
        headers=auth(),
    ).json()
    events = [row["event_type"] for row in audit]
    assert events.count("rollout_rolled_back") == 1


def test_rollback_blocks_stale_production_state(
    monkeypatch,
) -> None:
    state, rollout = _approved_and_applied_rollout(
        monkeypatch,
    )

    with SessionLocal() as session:
        product = session.get(
            ProductRecord,
            state["product"]["product_id"],
        )
        assert product is not None
        product.price_minor_units = 1400
        session.commit()

    monitor = client.get(
        (
            f"/v1/rollouts/"
            f"{rollout['rollout_id']}/monitor"
        ),
        headers=auth(),
    )
    assert monitor.status_code == 200
    assert monitor.json()["monitoring_status"] == "state_drift"

    response = client.post(
        (
            f"/v1/rollouts/"
            f"{rollout['rollout_id']}/rollback"
        ),
        headers=role_auth("incident-token"),
        json={
            "actor": "spoofed-incident-manager",
            "reason": "attempt stale rollback",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "production state changed since rollout"
    )

    product = client.get(
        f"/v1/products/{state['product']['product_id']}",
        headers=auth(),
    ).json()
    assert product["price_minor_units"] == 1400
