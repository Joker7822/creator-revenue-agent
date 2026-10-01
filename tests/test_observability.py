import json
import logging

from fastapi.testclient import TestClient

from api_server.main import app
from api_server.observability import (
    operational_metrics,
    operational_status_snapshot,
)


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_request_and_trace_ids_are_returned() -> None:
    response = client.get(
        "/health",
        headers={
            "X-Request-ID": "client-request-1234",
            "traceparent": (
                "00-4bf92f3577b34da6a3ce929d0e0e4736-"
                "00f067aa0ba902b7-01"
            ),
        },
    )

    assert response.status_code == 200
    assert (
        response.headers["X-Request-ID"]
        == "client-request-1234"
    )
    assert (
        response.headers["X-Trace-ID"]
        == "4bf92f3577b34da6a3ce929d0e0e4736"
    )


def test_invalid_request_id_is_replaced() -> None:
    response = client.get(
        "/health",
        headers={"X-Request-ID": "bad"},
    )

    assert response.status_code == 200
    generated = response.headers["X-Request-ID"]
    assert generated.startswith("req_")
    assert generated != "bad"
    assert len(response.headers["X-Trace-ID"]) == 32


def test_route_metrics_use_templates_not_resource_ids() -> None:
    first = client.get(
        "/v1/rollouts/roll-alpha",
        headers=auth(),
    )
    second = client.get(
        "/v1/rollouts/roll-beta",
        headers=auth(),
    )
    assert first.status_code == 404
    assert second.status_code == 404

    snapshot = operational_metrics.snapshot()
    rows = {
        row["route"]: row
        for row in snapshot["routes"]
    }
    key = "GET /v1/rollouts/{rollout_id}"
    assert key in rows
    assert rows[key]["requests"] == 2
    assert rows[key]["errors"] == 2
    assert not any(
        "roll-alpha" in route or "roll-beta" in route
        for route in rows
    )


def test_auth_rejection_is_an_incident_signal(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "OPS_ALERT_AUTH_REJECTION_THRESHOLD",
        "1",
    )

    rejected = client.get("/v1/ops/status")
    assert rejected.status_code == 401

    response = client.get(
        "/v1/ops/status",
        headers=auth(),
    )
    assert response.status_code == 200
    data = response.json()

    assert data["incident_signals"]["auth_rejections"] == 1
    alert = next(
        row
        for row in data["alerts"]
        if row["signal"] == "auth_rejections"
    )
    assert alert["triggered"] is True
    assert alert["severity"] == "warning"


def test_critical_signal_marks_operational_status_unhealthy(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "OPS_ALERT_ROLLOUT_FAILURE_THRESHOLD",
        "1",
    )
    operational_metrics.record(
        method="POST",
        route="/v1/change-sets/{change_set_id}/apply",
        status_code=409,
        duration_ms=12.5,
    )

    data = operational_status_snapshot()
    assert data["healthy"] is False
    assert (
        data["incident_signals"]["rollout_apply_failures"]
        == 1
    )


def test_structured_request_log_contains_correlation_ids(
    caplog,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="creator_revenue_agent.observability",
    )

    response = client.get(
        "/health",
        headers={"X-Request-ID": "request-log-1234"},
    )
    assert response.status_code == 200

    records = [
        record
        for record in caplog.records
        if record.name
        == "creator_revenue_agent.observability"
    ]
    assert records

    payload = json.loads(records[-1].message)
    assert payload["event"] == "http_request_completed"
    assert payload["request_id"] == "request-log-1234"
    assert payload["trace_id"] == response.headers["X-Trace-ID"]
    assert payload["method"] == "GET"
    assert payload["route"] == "/health"
    assert payload["status_code"] == 200
    assert "authorization" not in payload
    assert "body" not in payload
