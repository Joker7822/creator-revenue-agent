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


class RequestBodyLimitMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(
        self,
        scope,
        receive,
        send,
    ) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("method")
            not in {"POST", "PUT", "PATCH"}
        ):
            await self.app(scope, receive, send)
            return

        limit = request_body_limit_bytes()
        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                declared_length = int(
                    raw_length.decode("ascii")
                )
            except (ValueError, UnicodeDecodeError):
                declared_length = -1
            if declared_length > limit:
                await self._reject(scope, receive, send)
                return

        messages = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)

            if message["type"] == "http.disconnect":
                await self.app(
                    scope,
                    self._replay(messages),
                    send,
                )
                return

            if message["type"] != "http.request":
                continue

            total += len(message.get("body", b""))
            if total > limit:
                await self._reject(scope, receive, send)
                return

            if not message.get("more_body", False):
                break

        await self.app(
            scope,
            self._replay(messages),
            send,
        )

    @staticmethod
    def _replay(messages):
        index = 0

        async def replay():
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        return replay

    @staticmethod
    async def _reject(scope, receive, send) -> None:
        from fastapi.responses import JSONResponse

        response = JSONResponse(
            status_code=413,
            content={
                "detail": "request body too large",
                "error_code": "request_body_too_large",
            },
            headers={"Connection": "close"},
        )
        await response(scope, receive, send)


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
    raw = os.getenv(
        "MAX_REQUEST_BODY_BYTES",
        "1048576",
    )
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MAX_REQUEST_BODY_BYTES is invalid",
        ) from exc

    if value < 1 or value > 16_777_216:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MAX_REQUEST_BODY_BYTES is invalid",
        )
    return value


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
