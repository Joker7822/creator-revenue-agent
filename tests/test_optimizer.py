from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def setup_state() -> dict:
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
        json={"reviewer": "optimizer-reviewer"},
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

    return {
        "job": job,
        "publication": publication,
        "product": product,
    }


def test_optimizer_requires_active_product() -> None:
    job = client.post(
        "/v1/content/generate",
        headers=auth(),
        json={
            "campaign_type": "release",
            "target_segment": "subscribers",
            "price_cents": 1000,
            "creator_age": 21,
            "age_verified": True,
            "consent_verified": True,
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
        json={"reviewer": "optimizer-reviewer"},
    )
    assert approved.status_code == 200

    publication = client.post(
        "/v1/publish",
        headers=auth(),
        json={"job_id": job["job_id"]},
    ).json()

    response = client.post(
        "/v1/optimizer/proposals",
        headers=auth(),
        json={
            "publication_id": publication["publication_id"],
            "window": "7d",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "active product required"


def test_optimizer_low_sample_is_proposal_only() -> None:
    state = setup_state()

    response = client.post(
        "/v1/optimizer/proposals",
        headers=auth(),
        json={
            "publication_id": state["publication"]["publication_id"],
            "window": "7d",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending_review"
    actions = [row["action"] for row in data["recommendations"]]
    assert "collect_more_impressions" in actions
    assert "run_controlled_posting_time_experiment" in actions


def test_optimizer_suggests_bounded_lower_price_for_low_cvr() -> None:
    state = setup_state()
    publication_id = state["publication"]["publication_id"]
    product_id = state["product"]["product_id"]

    for i in range(100):
        client.post(
            "/v1/events",
            headers=auth(),
            json={
                "event_id": f"opt_imp_{i}",
                "publication_id": publication_id,
                "event_type": "impression",
            },
        )
    for i in range(25):
        client.post(
            "/v1/events",
            headers=auth(),
            json={
                "event_id": f"opt_click_{i}",
                "publication_id": publication_id,
                "event_type": "click",
            },
        )

    response = client.post(
        "/v1/optimizer/proposals",
        headers=auth(),
        json={
            "publication_id": publication_id,
            "window": "7d",
        },
    )
    assert response.status_code == 200

    price_tests = [
        row
        for row in response.json()["recommendations"]
        if row["type"] == "price_test"
    ]
    assert len(price_tests) == 1
    assert price_tests[0]["action"] == "test_lower_price"
    assert price_tests[0]["current_price_minor_units"] == 1500
    assert price_tests[0]["candidate_price_minor_units"] == 1350
    assert price_tests[0]["max_change_percent"] == 10

    product = client.get(
        f"/v1/products/{product_id}",
        headers=auth(),
    ).json()
    assert product["price_minor_units"] == 1500


def test_optimizer_approval_does_not_apply_change() -> None:
    state = setup_state()

    proposal = client.post(
        "/v1/optimizer/proposals",
        headers=auth(),
        json={
            "publication_id": state["publication"]["publication_id"],
            "window": "7d",
        },
    ).json()

    approved = client.post(
        f"/v1/optimizer/proposals/{proposal['proposal_id']}/approve",
        headers=auth(),
        json={
            "reviewer": "business-owner",
            "reason": "approve experiment plan only",
        },
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    product = client.get(
        f"/v1/products/{state['product']['product_id']}",
        headers=auth(),
    ).json()
    assert product["price_minor_units"] == 1500


def test_optimizer_decision_is_audited() -> None:
    state = setup_state()
    proposal = client.post(
        "/v1/optimizer/proposals",
        headers=auth(),
        json={
            "publication_id": state["publication"]["publication_id"],
            "window": "7d",
        },
    ).json()

    response = client.post(
        f"/v1/optimizer/proposals/{proposal['proposal_id']}/reject",
        headers=auth(),
        json={
            "reviewer": "business-owner",
            "reason": "insufficient evidence",
        },
    )
    assert response.status_code == 200

    audit = client.get(
        f"/v1/audit/{state['job']['job_id']}",
        headers=auth(),
    ).json()
    events = [row["event_type"] for row in audit]
    assert "optimizer_proposal_created" in events
    assert "optimizer_proposal_rejected" in events
