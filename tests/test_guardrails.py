from app.guardrails import preflight_guardrails


def test_allows_verified_adult_with_consent() -> None:
    result = preflight_guardrails(
        creator_age=21,
        age_verified=True,
        consent_verified=True,
        depicts_real_person=False,
        real_person_consent_verified=False,
    )
    assert result.allowed is True
    assert result.reasons == []


def test_rejects_unverified_age() -> None:
    result = preflight_guardrails(
        creator_age=21,
        age_verified=False,
        consent_verified=True,
        depicts_real_person=False,
        real_person_consent_verified=False,
    )
    assert result.allowed is False
    assert "age_verification_required" in result.reasons


def test_rejects_minor() -> None:
    result = preflight_guardrails(
        creator_age=17,
        age_verified=True,
        consent_verified=True,
        depicts_real_person=False,
        real_person_consent_verified=False,
    )
    assert result.allowed is False
    assert "adult_age_not_verified" in result.reasons


def test_real_person_requires_verified_consent() -> None:
    result = preflight_guardrails(
        creator_age=25,
        age_verified=True,
        consent_verified=True,
        depicts_real_person=True,
        real_person_consent_verified=False,
    )
    assert result.allowed is False
    assert "real_person_consent_required" in result.reasons
