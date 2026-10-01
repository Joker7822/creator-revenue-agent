# Observability and Incident Diagnostics

## Correlation

For each inbound HTTP request the API resolves a request ID and trace ID.

```text
X-Request-ID
X-Trace-ID
```

Valid caller request IDs are preserved. Invalid or missing IDs are replaced with `req_<uuid>`.

If a valid W3C `traceparent` is supplied, its 32-hex trace ID becomes `X-Trace-ID`. Otherwise a trace ID is generated.

The audit-anchor HTTP client propagates the same correlation context using `X-Request-ID` and a W3C `traceparent`.

## Structured request events

Each request produces an `http_request_completed` JSON event with:

- request_id
- trace_id
- method
- route template
- HTTP status
- duration_ms

Unhandled exceptions produce `http_request_unhandled_exception` with the exception type but not the exception message or request payload.

The application deliberately does not log request bodies, bearer tokens, webhook HMAC values, or authorization headers.

## Operational status

```text
GET /v1/ops/status
```

The response contains:

- process uptime
- total requests
- counts by HTTP status class
- counts by bounded error class
- incident-signal counters
- per-route request/error counts
- average and maximum route duration
- alert evaluations

Route labels use FastAPI templates such as:

```text
GET /v1/rollouts/{rollout_id}
```

rather than concrete IDs.

## Incident signals

Signals currently include:

```text
auth_rejections
verification_webhook_rejections
audit_anchor_failures
rollout_apply_failures
rollout_state_drift
rollback_failures
readiness_failures
server_or_dependency_5xx
```

A rollout monitor result of `state_drift` increments its signal even though the HTTP response is successful.

## Alert thresholds

Defaults:

```text
OPS_ALERT_5XX_THRESHOLD=1
OPS_ALERT_ROLLOUT_FAILURE_THRESHOLD=1
OPS_ALERT_ROLLOUT_DRIFT_THRESHOLD=1
OPS_ALERT_ROLLBACK_FAILURE_THRESHOLD=1
OPS_ALERT_AUDIT_ANCHOR_FAILURE_THRESHOLD=1
OPS_ALERT_WEBHOOK_REJECTION_THRESHOLD=5
OPS_ALERT_AUTH_REJECTION_THRESHOLD=20
OPS_ALERT_READINESS_FAILURE_THRESHOLD=1
```

Thresholds apply to counters accumulated since the current process started. They are useful as an internal safety surface, but production alerting should ingest these signals into durable monitoring with time-windowed rate alerts and multi-instance aggregation.
