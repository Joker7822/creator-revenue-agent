from __future__ import annotations

from typing import Any

import httpx

from app.config import settings


class CustomAPIError(RuntimeError):
    pass


class CustomAPIClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = (base_url or settings.custom_api_base_url).rstrip("/")
        self.token = token or settings.custom_api_token
        self.timeout_seconds = timeout_seconds

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "creator-revenue-agent/0.1",
        }

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.request(
                method,
                url,
                headers=self.headers,
                **kwargs,
            )

        if response.status_code >= 400:
            body = response.text[:500]
            raise CustomAPIError(
                f"{method} {path} failed with HTTP "
                f"{response.status_code}: {body}"
            )

        if not response.content:
            return {}

        data = response.json()
        if not isinstance(data, (dict, list)):
            raise CustomAPIError(
                f"{method} {path} returned unsupported JSON"
            )
        return data

    def create_verification(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/verifications",
            json=payload,
        )

    def get_verification(
        self,
        verification_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/verifications/{verification_id}",
        )

    def revoke_verification(
        self,
        verification_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/verifications/{verification_id}/revoke",
            json={"reason": reason},
        )

    def generate_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/content/generate", json=payload)

    def evaluate_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/policy/evaluate", json=payload)

    def create_approval(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/approvals", json=payload)

    def get_approval(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/approvals/{job_id}")

    def approve_job(
        self,
        job_id: str,
        *,
        reviewer: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/approvals/{job_id}/approve",
            json={"reviewer": reviewer, "reason": reason},
        )

    def reject_job(
        self,
        job_id: str,
        *,
        reviewer: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/approvals/{job_id}/reject",
            json={"reviewer": reviewer, "reason": reason},
        )

    def get_audit(self, job_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/v1/audit/{job_id}")
        if not isinstance(data, list):
            raise CustomAPIError("audit endpoint returned non-list JSON")
        return data

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/publish", json=payload)

    def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/products", json=payload)

    def record_transaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/transactions", json=payload)

    def get_revenue(
        self,
        *,
        since: str | None = None,
    ) -> dict[str, Any]:
        params = {"since": since} if since else None
        return self._request("GET", "/v1/revenue", params=params)

    def record_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/events", json=payload)

    def get_metrics(
        self,
        *,
        window: str = "7d",
        publication_id: str | None = None,
    ) -> dict[str, Any]:
        params = {"window": window}
        if publication_id:
            params["publication_id"] = publication_id
        return self._request("GET", "/v1/metrics", params=params)

    def create_experiment(
        self,
        *,
        proposal_id: str,
        recommendation_index: int,
        owner: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/experiments",
            json={
                "proposal_id": proposal_id,
                "recommendation_index": recommendation_index,
                "owner": owner,
            },
        )

    def start_experiment(
        self,
        experiment_id: str,
        *,
        actor: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/experiments/{experiment_id}/start",
            json={"actor": actor},
        )

    def assign_experiment_subject(
        self,
        experiment_id: str,
        *,
        subject_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/experiments/{experiment_id}/assignments",
            json={"subject_key": subject_key},
        )

    def record_experiment_event(
        self,
        experiment_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/experiments/{experiment_id}/events",
            json=payload,
        )

    def link_experiment_transaction(
        self,
        experiment_id: str,
        *,
        transaction_id: str,
        assignment_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/experiments/{experiment_id}/transactions",
            json={
                "transaction_id": transaction_id,
                "assignment_id": assignment_id,
            },
        )

    def get_experiment_results(
        self,
        experiment_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/experiments/{experiment_id}/results",
        )

    def get_experiment_statistics(
        self,
        experiment_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/experiments/{experiment_id}/statistics",
        )

    def create_experiment_review(
        self,
        experiment_id: str,
        *,
        decision: str,
        reviewer: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/experiments/{experiment_id}/reviews",
            json={
                "decision": decision,
                "reviewer": reviewer,
                "reason": reason,
            },
        )

    def create_change_set(
        self,
        *,
        review_id: str,
        created_by: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/change-sets",
            json={
                "review_id": review_id,
                "created_by": created_by,
            },
        )

    def approve_change_set(
        self,
        change_set_id: str,
        *,
        actor: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/change-sets/{change_set_id}/approve",
            json={"actor": actor, "reason": reason},
        )

    def apply_change_set(
        self,
        change_set_id: str,
        *,
        actor: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/change-sets/{change_set_id}/apply",
            json={"actor": actor},
        )

    def monitor_rollout(
        self,
        rollout_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/rollouts/{rollout_id}/monitor",
        )

    def rollback_rollout(
        self,
        rollout_id: str,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/rollouts/{rollout_id}/rollback",
            json={"actor": actor, "reason": reason},
        )

    def issue_service_credential(
        self,
        *,
        subject: str,
        roles: list[str],
        ttl_seconds: int = 900,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/auth/credentials",
            json={
                "subject": subject,
                "roles": roles,
                "ttl_seconds": ttl_seconds,
            },
        )

    def get_service_credential(
        self,
        credential_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/auth/credentials/{credential_id}",
        )

    def revoke_service_credential(
        self,
        credential_id: str,
        *,
        reason: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/auth/credentials/{credential_id}/revoke",
            json={"reason": reason},
        )

    def create_audit_anchor(self) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/audit/anchors",
        )

    def verify_audit_anchor(self) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/audit/anchors/verify",
        )

    def get_audit_integrity(self) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/audit/integrity",
        )

    def get_signing_key_status(self) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/auth/signing-keys",
        )

    def get_verification_webhook_key_status(
        self,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/auth/verification-webhook-keys",
        )

    def complete_experiment(
        self,
        experiment_id: str,
        *,
        actor: str,
        outcome: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/experiments/{experiment_id}/complete",
            json={"actor": actor, "outcome": outcome},
        )

    def create_optimization_proposal(
        self,
        *,
        publication_id: str,
        window: str = "7d",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/optimizer/proposals",
            json={
                "publication_id": publication_id,
                "window": window,
            },
        )

    def approve_optimization_proposal(
        self,
        proposal_id: str,
        *,
        reviewer: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/v1/optimizer/proposals/{proposal_id}/approve",
            json={"reviewer": reviewer, "reason": reason},
        )
