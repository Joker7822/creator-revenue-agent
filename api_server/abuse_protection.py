from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status

from api_server.auth import (
    ServicePrincipal,
    require_service_token,
)


@dataclass
class Window:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    MAX_ENTRIES = 10_000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], Window] = {}

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()

    def check(
        self,
        *,
        bucket: str,
        subject: str,
        limit: int,
        window_seconds: int = 60,
    ) -> None:
        now = time.monotonic()
        key = (bucket, subject)

        with self._lock:
            current = self._windows.get(key)
            if (
                current is None
                or now - current.started_at >= window_seconds
            ):
                if current is None and len(self._windows) >= self.MAX_ENTRIES:
                    expired = [
                        existing_key
                        for existing_key, window in self._windows.items()
                        if now - window.started_at >= window_seconds
                    ]
                    for existing_key in expired:
                        self._windows.pop(existing_key, None)

                    if len(self._windows) >= self.MAX_ENTRIES:
                        oldest_key = min(
                            self._windows,
                            key=lambda existing_key: (
                                self._windows[existing_key].started_at
                            ),
                        )
                        self._windows.pop(oldest_key, None)

                self._windows[key] = Window(
                    started_at=now,
                    count=1,
                )
                return

            if current.count >= limit:
                retry_after = max(
                    1,
                    int(
                        window_seconds
                        - (now - current.started_at)
                    )
                    + 1,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="rate limit exceeded",
                    headers={
                        "Retry-After": str(retry_after),
                    },
                )

            current.count += 1


rate_limiter = FixedWindowRateLimiter()


def _limit(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name} is invalid",
        ) from exc

    if value < 1 or value > 1_000_000:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name} is invalid",
        )
    return value


def request_body_limit_bytes() -> int:
    return _limit(
        "MAX_REQUEST_BODY_BYTES",
        1_048_576,
    )


def _subject_rate_limit(
    *,
    bucket: str,
    env_name: str,
    default: int,
    principal: ServicePrincipal,
) -> None:
    rate_limiter.check(
        bucket=bucket,
        subject=principal.subject,
        limit=_limit(env_name, default),
    )


def require_billing_rate_limit(
    principal: ServicePrincipal = Depends(
        require_service_token
    ),
) -> None:
    _subject_rate_limit(
        bucket="billing_write",
        env_name="BILLING_RATE_LIMIT_PER_MINUTE",
        default=120,
        principal=principal,
    )


def require_credential_rate_limit(
    principal: ServicePrincipal = Depends(
        require_service_token
    ),
) -> None:
    _subject_rate_limit(
        bucket="credential_admin",
        env_name="CREDENTIAL_RATE_LIMIT_PER_MINUTE",
        default=30,
        principal=principal,
    )


def require_rollout_rate_limit(
    principal: ServicePrincipal = Depends(
        require_service_token
    ),
) -> None:
    _subject_rate_limit(
        bucket="rollout_mutation",
        env_name="ROLLOUT_RATE_LIMIT_PER_MINUTE",
        default=30,
        principal=principal,
    )


def require_verification_webhook_rate_limit(
    request: Request,
    x_verification_provider: str = Header(
        alias="X-Verification-Provider",
    ),
) -> None:
    provider = x_verification_provider.strip()
    if not provider or len(provider) > 120:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid verification provider",
        )

    client_host = (
        request.client.host
        if request.client is not None
        else "unknown"
    )
    rate_limiter.check(
        bucket="verification_webhook",
        subject=f"{provider}:{client_host}",
        limit=_limit(
            "VERIFICATION_WEBHOOK_RATE_LIMIT_PER_MINUTE",
            300,
        ),
    )
