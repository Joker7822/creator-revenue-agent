import os

from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_record(
    *,
    subject_ref: str,
    kind: str,
    age_years: int | None = None,
) -> dict:
    payload = {
        "subject_ref": subject_ref,
        "kind": kind,
        "source": "test-verification-provider",
        "source_record_ref": f"external-{kind}",
    }
    if age_years is not None:
        payload["age_years"] = age_years

    response = client.post(
        "/v1/verifications",
        headers=bearer("verification-token"),
        json=payload,
    )
    assert response.status_code == 200
    return response.json()


def trusted_job(
    *,
    subject_ref: str = "creator-verified-1",
) -> tuple[dict, dict, dict]:
    age = create_record(
        subject_ref=subject_ref,
        kind="age",
        age_years=21,
    )
    consent = create_record(
        subject_ref=subject_ref,
        kind="creator_consent",
    )

    response = client.post(
        "/v1/content/generate",
        headers=bearer("test-token"),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "creator_age": 99,
            "age_verified": False,
            "consent_verified": False,
            "depicts_real_person": False,
            "real_person_consent_verified": True,
            "creator_ref": subject_ref,
            "age_verification_id": age["verification_id"],
            "consent_verification_id": consent["verification_id"],
        },
    )
    assert response.status_code == 200
    return response.json(), age, consent


def test_trusted_records_override_self_asserted_flags(
    monkeypatch,
) -> None:
    monkeypatch.setenv("REQUIRE_TRUSTED_VERIFICATION", "true")
    job, age, consent = trusted_job()

    assert job["creator_age"] == 21
    assert job["age_verified"] is True
    assert job["consent_verified"] is True
    assert job["real_person_consent_verified"] is False
    assert job["age_verification_id"] == age["verification_id"]
    assert job["consent_verification_id"] == consent["verification_id"]


def test_trusted_mode_rejects_boolean_only_verification(
    monkeypatch,
) -> None:
    monkeypatch.setenv("REQUIRE_TRUSTED_VERIFICATION", "true")

    response = client.post(
        "/v1/content/generate",
        headers=bearer("test-token"),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "creator_age": 30,
            "age_verified": True,
            "consent_verified": True,
            "depicts_real_person": False,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "creator_ref required for trusted verification"
    )


def test_verification_subject_mismatch_is_blocked(
    monkeypatch,
) -> None:
    monkeypatch.setenv("REQUIRE_TRUSTED_VERIFICATION", "true")
    age = create_record(
        subject_ref="creator-a",
        kind="age",
        age_years=25,
    )
    consent = create_record(
        subject_ref="creator-b",
        kind="creator_consent",
    )

    response = client.post(
        "/v1/content/generate",
        headers=bearer("test-token"),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "depicts_real_person": False,
            "creator_ref": "creator-a",
            "age_verification_id": age["verification_id"],
            "consent_verification_id": consent["verification_id"],
        },
    )
    assert response.status_code == 409
    assert "subject mismatch" in response.json()["detail"]


def test_revocation_invalidates_policy_and_blocks_publish(
    monkeypatch,
) -> None:
    monkeypatch.setenv("REQUIRE_TRUSTED_VERIFICATION", "true")
    job, _, consent = trusted_job(
        subject_ref="creator-revoke-1",
    )

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
    approved = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=bearer("reviewer-token"),
        json={"reason": "review complete"},
    )
    assert approved.status_code == 200

    revoked = client.post(
        (
            f"/v1/verifications/"
            f"{consent['verification_id']}/revoke"
        ),
        headers=bearer("verification-token"),
        json={"reason": "consent withdrawn"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    publish = client.post(
        "/v1/publish",
        headers=bearer("publisher-token"),
        json={"job_id": job["job_id"]},
    )
    assert publish.status_code == 409

    reevaluated = client.post(
        "/v1/policy/evaluate",
        headers=bearer("test-token"),
        json={"job_id": job["job_id"]},
    )
    assert reevaluated.status_code == 200
    assert reevaluated.json()["allowed"] is False
    assert "creator_consent_required" in (
        reevaluated.json()["reasons"]
    )


def test_verification_writer_role_is_required() -> None:
    response = client.post(
        "/v1/verifications",
        headers=bearer("reader-token"),
        json={
            "subject_ref": "creator-x",
            "kind": "age",
            "source": "test",
            "age_years": 21,
        },
    )
    assert response.status_code == 403
