from fastapi.testclient import TestClient

from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_required(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-token")

    response = client.post(
        "/v1/policy/evaluate",
        json={},
    )
    assert response.status_code == 401


def test_generate_campaign_metadata(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-token")

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
    data = response.json()
    assert data["job_id"].startswith("job_")
    assert data["asset_ref"] is None
    assert data["creator_age"] == 21
    assert data["age_verified"] is True


def test_policy_accepts_verified_adult(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-token")

    response = client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={
            "creator_age": 21,
            "age_verified": True,
            "consent_verified": True,
            "depicts_real_person": False,
            "real_person_consent_verified": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"allowed": True, "reasons": []}


def test_policy_rejects_minor(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-token")

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
    assert "adult_age_not_verified" in response.json()["reasons"]


def test_policy_rejects_github_asset(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-token")

    response = client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={
            "creator_age": 25,
            "age_verified": True,
            "consent_verified": True,
            "asset_ref": "https://github.com/example/repo/blob/main/media/x",
        },
    )

    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert (
        "github_asset_storage_not_allowed"
        in response.json()["reasons"]
    )
