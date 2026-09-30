from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reasons: list[str]


def preflight_guardrails(
    *,
    creator_age: int | None,
    age_verified: bool,
    consent_verified: bool,
    depicts_real_person: bool,
    real_person_consent_verified: bool,
    min_creator_age: int = 18,
) -> GuardrailResult:
    reasons: list[str] = []

    if creator_age is None or creator_age < min_creator_age:
        reasons.append("adult_age_not_verified")

    if not age_verified:
        reasons.append("age_verification_required")

    if not consent_verified:
        reasons.append("creator_consent_required")

    if depicts_real_person and not real_person_consent_verified:
        reasons.append("real_person_consent_required")

    return GuardrailResult(allowed=not reasons, reasons=reasons)
