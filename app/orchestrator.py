from __future__ import annotations

from typing import Any

from app.api.client import CustomAPIClient
from app.config import settings
from app.guardrails import preflight_guardrails


class Orchestrator:
    def __init__(self, api: CustomAPIClient | None = None) -> None:
        self.api = api or CustomAPIClient()

    def create_job(self, brief: dict[str, Any]) -> dict[str, Any]:
        generated = self.api.generate_content(brief)

        local = preflight_guardrails(
            creator_age=generated.get("creator_age"),
            age_verified=generated.get("age_verified", False),
            consent_verified=generated.get("consent_verified", False),
            depicts_real_person=generated.get("depicts_real_person", False),
            real_person_consent_verified=generated.get(
                "real_person_consent_verified",
                False,
            ),
            min_creator_age=settings.min_creator_age,
        )

        if not local.allowed:
            return {
                "job_id": generated.get("job_id"),
                "status": "rejected",
                "source": "local_guardrails",
                "reasons": local.reasons,
            }

        policy = self.api.evaluate_policy(
            {
                "job_id": generated["job_id"],
                "creator_age": generated["creator_age"],
                "age_verified": generated["age_verified"],
                "consent_verified": generated["consent_verified"],
                "depicts_real_person": generated.get(
                    "depicts_real_person",
                    False,
                ),
                "real_person_consent_verified": generated.get(
                    "real_person_consent_verified",
                    False,
                ),
                "asset_ref": generated.get("asset_ref"),
            }
        )

        if policy.get("allowed") is not True:
            return {
                "job_id": generated["job_id"],
                "status": "rejected",
                "source": "policy_api",
                "reasons": policy.get("reasons", ["policy_rejected"]),
            }

        approval = self.api.create_approval(
            {
                "job_id": generated["job_id"],
                "required": settings.require_human_review,
            }
        )

        return {
            "job_id": generated["job_id"],
            "status": approval.get("status", "pending_review"),
        }

    def publish_if_approved(self, job_id: str) -> dict[str, Any]:
        approval = self.api.get_approval(job_id)

        if approval.get("status") != "approved":
            return {
                "job_id": job_id,
                "status": "not_published",
                "reason": "approval_required",
            }

        return self.api.publish({"job_id": job_id})

    def metrics(self, window: str = "7d") -> dict[str, Any]:
        return self.api.get_metrics(window=window)
