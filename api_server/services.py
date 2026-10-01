from __future__ import annotations

import os
import re
from uuid import uuid4

from app.guardrails import preflight_guardrails
from api_server.schemas import (
    ContentGenerateRequest,
    ContentGenerateResponse,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
)


def _safe_label(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9 _-]+", "", value).strip()
    return value[:80] or "premium"


def generate_campaign_metadata(
    request: ContentGenerateRequest,
) -> ContentGenerateResponse:
    campaign = _safe_label(request.campaign_type).replace("_", " ")
    segment = _safe_label(request.target_segment).replace("_", " ")

    return ContentGenerateResponse(
        job_id=f"job_{uuid4().hex}",
        title=f"{campaign.title()} campaign",
        teaser=f"New members-only release for {segment}.",
        price_cents=request.price_cents,
        creator_age=request.creator_age,
        age_verified=request.age_verified,
        consent_verified=request.consent_verified,
        depicts_real_person=request.depicts_real_person,
        real_person_consent_verified=(
            request.real_person_consent_verified
        ),
        creator_ref=request.creator_ref,
        age_verification_id=request.age_verification_id,
        consent_verification_id=request.consent_verification_id,
        real_person_consent_verification_id=(
            request.real_person_consent_verification_id
        ),
        asset_ref=None,
    )


def evaluate_policy(
    request: PolicyEvaluateRequest,
) -> PolicyEvaluateResponse:
    min_age = int(os.getenv("MIN_CREATOR_AGE", "18"))

    result = preflight_guardrails(
        creator_age=request.creator_age,
        age_verified=request.age_verified,
        consent_verified=request.consent_verified,
        depicts_real_person=request.depicts_real_person,
        real_person_consent_verified=(
            request.real_person_consent_verified
        ),
        min_creator_age=min_age,
    )

    reasons = list(result.reasons)

    if request.asset_ref:
        ref = request.asset_ref.lower()
        if "github.com" in ref or ref.startswith("github:"):
            reasons.append("github_asset_storage_not_allowed")

    return PolicyEvaluateResponse(
        allowed=not reasons,
        reasons=reasons,
    )
