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
        self.base_url = (
            base_url or settings.custom_api_base_url
        ).rstrip("/")
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

        with httpx.Client(
            timeout=self.timeout_seconds,
        ) as client:
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

    def generate_content(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/content/generate",
            json=payload,
        )

    def evaluate_policy(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/policy/evaluate",
            json=payload,
        )

    def create_approval(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/approvals",
            json=payload,
        )

    def get_approval(
        self,
        job_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v1/approvals/{job_id}",
        )

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
            json={
                "reviewer": reviewer,
                "reason": reason,
            },
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
            json={
                "reviewer": reviewer,
                "reason": reason,
            },
        )

    def get_audit(
        self,
        job_id: str,
    ) -> list[dict[str, Any]]:
        data = self._request(
            "GET",
            f"/v1/audit/{job_id}",
        )
        if not isinstance(data, list):
            raise CustomAPIError(
                "audit endpoint returned non-list JSON"
            )
        return data

    def publish(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/publish",
            json=payload,
        )

    def create_product(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/products",
            json=payload,
        )

    def get_revenue(
        self,
        *,
        since: str | None = None,
    ) -> dict[str, Any]:
        params = (
            {"since": since}
            if since
            else None
        )
        return self._request(
            "GET",
            "/v1/revenue",
            params=params,
        )

    def record_event(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/events",
            json=payload,
        )

    def get_metrics(
        self,
        *,
        window: str = "7d",
    ) -> dict[str, Any]:
        return self._request(
            "GET",
            "/v1/metrics",
            params={"window": window},
        )
