import base64
import json

from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def issue(
    *,
    subject: str,
    roles: list[str],
    ttl_seconds: int = 120,
) -> dict:
    response = client.post(
        "/v1/auth/credentials",
        headers=bearer("credential-admin-token"),
        json={
            "subject": subject,
            "roles": roles,
            "ttl_seconds": ttl_seconds,
        },
    )
    assert response.status_code == 200
    return response.json()


def payload(token: str) -> dict:
    segment = token.split(".")[1]
    segment += "=" * (-len(segment) % 4)
    return json.loads(
        base64.urlsafe_b64decode(segment).decode("utf-8")
    )


def create_pending_job() -> dict:
    job = client.post(
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
    ).json()
    policy = client.post(
        "/v1/policy/evaluate",
        headers=bearer("test-token"),
        json={"job_id": job["job_id"]},
    )
    assert policy.status_code == 200
    approval = client.post(
        "/v1/approvals",
        headers=bearer("test-token"),
        json={"job_id": job["job_id"], "required": True},
    )
    assert approval.status_code == 200
    return job


def test_issued_credential_is_short_lived_and_signed() -> None:
    credential = issue(
        subject="short-lived-reviewer",
        roles=["reviewer"],
        ttl_seconds=120,
    )
    claims = payload(credential["access_token"])

    assert credential["key_id"] == "test-old"
    assert claims["jti"] == credential["credential_id"]
    assert claims["sub"] == "short-lived-reviewer"
    assert claims["roles"] == ["reviewer"]
    assert claims["exp"] - claims["iat"] == 120


def test_signed_credential_drives_rbac_identity() -> None:
    credential = issue(
        subject="jwt-reviewer-service",
        roles=["reviewer"],
    )
    job = create_pending_job()

    response = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=bearer(credential["access_token"]),
        json={"reviewer": "spoofed-static-name"},
    )
    assert response.status_code == 200
    assert response.json()["reviewer"] == "jwt-reviewer-service"


def test_revoked_credential_is_rejected() -> None:
    credential = issue(
        subject="revocable-reviewer",
        roles=["reviewer"],
    )

    revoke = client.post(
        (
            f"/v1/auth/credentials/"
            f"{credential['credential_id']}/revoke"
        ),
        headers=bearer("credential-admin-token"),
        json={"reason": "rotation test"},
    )
    assert revoke.status_code == 200
    assert revoke.json()["active"] is False
    assert revoke.json()["revoked_by"] == (
        "credential-admin-service"
    )

    job = create_pending_job()
    denied = client.post(
        f"/v1/approvals/{job['job_id']}/approve",
        headers=bearer(credential["access_token"]),
        json={},
    )
    assert denied.status_code == 401
    assert denied.json()["detail"] == (
        "service credential has been revoked"
    )


def test_signing_key_rotation_accepts_overlap_then_retires_old(
    monkeypatch,
) -> None:
    old_credential = issue(
        subject="old-key-reader",
        roles=["reader"],
    )

    monkeypatch.setenv(
        "SERVICE_JWT_ACTIVE_KID",
        "test-new",
    )
    new_credential = issue(
        subject="new-key-reader",
        roles=["reader"],
    )

    old_ok = client.get(
        "/v1/revenue",
        headers=bearer(old_credential["access_token"]),
    )
    new_ok = client.get(
        "/v1/revenue",
        headers=bearer(new_credential["access_token"]),
    )
    assert old_ok.status_code == 200
    assert new_ok.status_code == 200

    monkeypatch.setenv(
        "SERVICE_JWT_KEYS_JSON",
        json.dumps(
            {
                "test-new": (
                    "new-signing-secret-0000000000000002"
                )
            }
        ),
    )

    old_denied = client.get(
        "/v1/revenue",
        headers=bearer(old_credential["access_token"]),
    )
    new_still_ok = client.get(
        "/v1/revenue",
        headers=bearer(new_credential["access_token"]),
    )
    assert old_denied.status_code == 401
    assert old_denied.json()["detail"] == (
        "service credential signing key is not active"
    )
    assert new_still_ok.status_code == 200


def test_key_status_exposes_ids_not_secrets() -> None:
    response = client.get(
        "/v1/auth/signing-keys",
        headers=bearer("credential-admin-token"),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["active_key_id"] == "test-old"
    assert set(data["configured_key_ids"]) == {
        "test-old",
        "test-new",
    }
    assert "secret" not in json.dumps(data).lower()
