from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter, defaultdict
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


logger = logging.getLogger(
    "creator_revenue_agent.observability"
)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_TRACEPARENT_RE = re.compile(
    r"^[\da-f]{2}-([\da-f]{32})-([\da-f]{16})-[\da-f]{2}$"
)

_request_id: ContextVar[str | None] = ContextVar(
    "request_id",
    default=None,
)
_trace_id: ContextVar[str | None] = ContextVar(
    "trace_id",
    default=None,
)


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    trace_id: str


def resolve_request_context(
    *,
    request_id_header: str | None,
    traceparent_header: str | None,
) -> RequestContext:
    request_id = (
        request_id_header
        if (
            request_id_header
            and _REQUEST_ID_RE.fullmatch(request_id_header)
        )
        else f"req_{uuid4().hex}"
    )

    trace_id: str | None = None
    if traceparent_header:
        match = _TRACEPARENT_RE.fullmatch(
            traceparent_header.strip().lower()
        )
        if match is not None:
            candidate = match.group(1)
            if candidate != "0" * 32:
                trace_id = candidate

    if trace_id is None:
        trace_id = uuid4().hex

    return RequestContext(
        request_id=request_id,
        trace_id=trace_id,
    )


def bind_request_context(context: RequestContext):
    request_token = _request_id.set(context.request_id)
    trace_token = _trace_id.set(context.trace_id)
    return request_token, trace_token


def reset_request_context(tokens) -> None:
    request_token, trace_token = tokens
    _request_id.reset(request_token)
    _trace_id.reset(trace_token)


def current_request_id() -> str | None:
    return _request_id.get()


def current_trace_id() -> str | None:
    return _trace_id.get()


def outbound_trace_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    request_id = current_request_id()
    trace_id = current_trace_id()
    if request_id:
        headers["X-Request-ID"] = request_id
    if trace_id:
        span_id = uuid4().hex[:16]
        headers["traceparent"] = (
            f"00-{trace_id}-{span_id}-01"
        )
    return headers


def _structured_log(
    level: int,
    event: str,
    **fields: Any,
) -> None:
    payload = {
        "event": event,
        "request_id": current_request_id(),
        "trace_id": current_trace_id(),
        **fields,
    }
    logger.log(
        level,
        json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ),
    )


def log_request_completed(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_ms: float,
) -> None:
    level = (
        logging.ERROR
        if status_code >= 500
        else logging.WARNING
        if status_code >= 400
        else logging.INFO
    )
    _structured_log(
        level,
        "http_request_completed",
        method=method,
        route=route,
        status_code=status_code,
        duration_ms=round(duration_ms, 3),
    )


def log_unhandled_exception(
    *,
    method: str,
    route: str,
    duration_ms: float,
    exception_type: str,
) -> None:
    _structured_log(
        logging.ERROR,
        "http_request_unhandled_exception",
        method=method,
        route=route,
        status_code=500,
        duration_ms=round(duration_ms, 3),
        exception_type=exception_type,
    )


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


def error_classification(
    status_code: int,
) -> str | None:
    if status_code < 400:
        return None
    if status_code in {401, 403}:
        return "auth_rejection"
    if status_code == 409:
        return "state_conflict"
    if status_code == 422:
        return "validation_error"
    if status_code in {502, 503, 504}:
        return "dependency_or_availability_failure"
    if status_code >= 500:
        return "server_error"
    return "client_error"


class OperationalMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._requests_total = 0
        self._status_classes: Counter[str] = Counter()
        self._errors: Counter[str] = Counter()
        self._incident_signals: Counter[str] = Counter()
        self._route_requests: Counter[str] = Counter()
        self._route_errors: Counter[str] = Counter()
        self._route_latency_sum_ms: dict[str, float] = defaultdict(
            float
        )
        self._route_latency_max_ms: dict[str, float] = defaultdict(
            float
        )

    def reset(self) -> None:
        with self._lock:
            self._started = time.monotonic()
            self._requests_total = 0
            self._status_classes.clear()
            self._errors.clear()
            self._incident_signals.clear()
            self._route_requests.clear()
            self._route_errors.clear()
            self._route_latency_sum_ms.clear()
            self._route_latency_max_ms.clear()

    def record(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        key = f"{method.upper()} {route}"
        classification = error_classification(status_code)

        with self._lock:
            self._requests_total += 1
            self._status_classes[
                _status_class(status_code)
            ] += 1
            self._route_requests[key] += 1
            self._route_latency_sum_ms[key] += duration_ms
            self._route_latency_max_ms[key] = max(
                self._route_latency_max_ms[key],
                duration_ms,
            )

            if classification is not None:
                self._errors[classification] += 1
                self._route_errors[key] += 1

            if status_code in {401, 403}:
                self._incident_signals["auth_rejections"] += 1

            if status_code == 429:
                self._incident_signals[
                    "rate_limit_rejections"
                ] += 1

            if status_code == 413:
                self._incident_signals[
                    "oversized_request_rejections"
                ] += 1

            if (
                route == "/v1/webhooks/verifications"
                and status_code >= 400
            ):
                self._incident_signals[
                    "verification_webhook_rejections"
                ] += 1

            if (
                route.startswith("/v1/audit/anchors")
                and status_code >= 400
            ):
                self._incident_signals[
                    "audit_anchor_failures"
                ] += 1

            if (
                route
                == "/v1/change-sets/{change_set_id}/apply"
                and status_code >= 400
            ):
                self._incident_signals[
                    "rollout_apply_failures"
                ] += 1

            if (
                route
                == "/v1/rollouts/{rollout_id}/rollback"
                and status_code >= 400
            ):
                self._incident_signals[
                    "rollback_failures"
                ] += 1

            if route == "/ready" and status_code >= 500:
                self._incident_signals[
                    "readiness_failures"
                ] += 1

            if status_code >= 500:
                self._incident_signals[
                    "server_or_dependency_5xx"
                ] += 1

    def record_signal(
        self,
        signal: str,
        *,
        count: int = 1,
    ) -> None:
        if count <= 0:
            return
        with self._lock:
            self._incident_signals[signal] += count

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            routes = []
            for key in sorted(self._route_requests):
                count = self._route_requests[key]
                error_count = self._route_errors[key]
                total_latency = self._route_latency_sum_ms[key]
                routes.append(
                    {
                        "route": key,
                        "requests": count,
                        "errors": error_count,
                        "average_duration_ms": (
                            round(total_latency / count, 3)
                            if count
                            else 0.0
                        ),
                        "max_duration_ms": round(
                            self._route_latency_max_ms[key],
                            3,
                        ),
                    }
                )

            return {
                "uptime_seconds": round(
                    time.monotonic() - self._started,
                    3,
                ),
                "requests_total": self._requests_total,
                "status_classes": dict(
                    sorted(self._status_classes.items())
                ),
                "errors_by_class": dict(
                    sorted(self._errors.items())
                ),
                "incident_signals": dict(
                    sorted(self._incident_signals.items())
                ),
                "routes": routes,
            }


operational_metrics = OperationalMetrics()


def request_route_template(scope: dict[str, Any]) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return "__unmatched__"



def _threshold(name: str, default: int) -> int:
    import os

    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, min(value, 1_000_000))


def operational_status_snapshot() -> dict[str, Any]:
    snapshot = operational_metrics.snapshot()
    signals = snapshot["incident_signals"]

    rules = (
        (
            "server_or_dependency_5xx",
            "OPS_ALERT_5XX_THRESHOLD",
            1,
            "critical",
        ),
        (
            "rollout_apply_failures",
            "OPS_ALERT_ROLLOUT_FAILURE_THRESHOLD",
            1,
            "critical",
        ),
        (
            "rollout_state_drift",
            "OPS_ALERT_ROLLOUT_DRIFT_THRESHOLD",
            1,
            "critical",
        ),
        (
            "rollback_failures",
            "OPS_ALERT_ROLLBACK_FAILURE_THRESHOLD",
            1,
            "critical",
        ),
        (
            "audit_anchor_failures",
            "OPS_ALERT_AUDIT_ANCHOR_FAILURE_THRESHOLD",
            1,
            "critical",
        ),
        (
            "verification_webhook_rejections",
            "OPS_ALERT_WEBHOOK_REJECTION_THRESHOLD",
            5,
            "warning",
        ),
        (
            "auth_rejections",
            "OPS_ALERT_AUTH_REJECTION_THRESHOLD",
            20,
            "warning",
        ),
        (
            "rate_limit_rejections",
            "OPS_ALERT_RATE_LIMIT_REJECTION_THRESHOLD",
            20,
            "warning",
        ),
        (
            "oversized_request_rejections",
            "OPS_ALERT_OVERSIZED_REQUEST_THRESHOLD",
            5,
            "warning",
        ),
        (
            "readiness_failures",
            "OPS_ALERT_READINESS_FAILURE_THRESHOLD",
            1,
            "critical",
        ),
    )

    alerts = []
    for signal, env_name, default, severity in rules:
        count = int(signals.get(signal, 0))
        threshold = _threshold(env_name, default)
        alerts.append(
            {
                "signal": signal,
                "severity": severity,
                "count": count,
                "threshold": threshold,
                "triggered": count >= threshold,
            }
        )

    snapshot["alerts"] = alerts
    snapshot["healthy"] = not any(
        row["triggered"] and row["severity"] == "critical"
        for row in alerts
    )
    return snapshot
