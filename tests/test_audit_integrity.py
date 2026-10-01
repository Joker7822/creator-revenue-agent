import json

from fastapi.testclient import TestClient
from sqlalchemy import delete, update

from api_server.db import AuditEvent, SessionLocal
from api_server.main import app


client = TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def create_job_with_audit() -> dict:
    response = client.post(
        "/v1/content/generate",
        headers=auth(),
        json={
            "campaign_type": "members_only_release",
            "target_segment": "subscribers",
            "price_cents": 1500,
            "creator_age": 21,
            "age_verified": True,
            "consent_verified": True,
            "depicts_real_person": False,
        },
    )
    assert response.status_code == 200
    job = response.json()

    policy = client.post(
        "/v1/policy/evaluate",
        headers=auth(),
        json={"job_id": job["job_id"]},
    )
    assert policy.status_code == 200
    return job


def test_audit_chain_is_valid_and_exposes_hashes() -> None:
    job = create_job_with_audit()

    events = client.get(
        f"/v1/audit/{job['job_id']}",
        headers=auth(),
    )
    assert events.status_code == 200
    rows = events.json()
    assert len(rows) == 2
    assert rows[0]["previous_hash"] == "0" * 64
    assert rows[0]["hash_key_id"] == "test-audit-2026-10"
    assert len(rows[0]["event_hash"]) == 64
    assert rows[1]["previous_hash"] == rows[0]["event_hash"]

    integrity = client.get(
        "/v1/audit/integrity",
        headers=auth(),
    )
    assert integrity.status_code == 200
    data = integrity.json()
    assert data["valid"] is True
    assert data["checked_events"] == 2
    assert data["head_event_id"] == rows[-1]["id"]
    assert data["head_hash"] == rows[-1]["event_hash"]


def test_payload_tampering_is_detected() -> None:
    job = create_job_with_audit()

    with SessionLocal() as session:
        first = session.query(AuditEvent).order_by(
            AuditEvent.id.asc()
        ).first()
        assert first is not None
        session.execute(
            update(AuditEvent)
            .where(AuditEvent.id == first.id)
            .values(payload_json=json.dumps({"tampered": True}))
        )
        session.commit()
        first_id = first.id

    integrity = client.get(
        "/v1/audit/integrity",
        headers=auth(),
    )
    assert integrity.status_code == 200
    data = integrity.json()
    assert data["valid"] is False
    assert data["first_invalid_event_id"] == first_id
    assert data["reason"] == "event_hash_mismatch"


def test_tail_deletion_is_detected_by_chain_head() -> None:
    create_job_with_audit()

    with SessionLocal() as session:
        last = session.query(AuditEvent).order_by(
            AuditEvent.id.desc()
        ).first()
        assert last is not None
        session.execute(
            delete(AuditEvent).where(AuditEvent.id == last.id)
        )
        session.commit()

    integrity = client.get(
        "/v1/audit/integrity",
        headers=auth(),
    )
    assert integrity.status_code == 200
    data = integrity.json()
    assert data["valid"] is False
    assert data["reason"] == "chain_head_mismatch"


def test_middle_deletion_breaks_previous_hash_link() -> None:
    job = create_job_with_audit()

    approval = client.post(
        "/v1/approvals",
        headers=auth(),
        json={"job_id": job["job_id"], "required": True},
    )
    assert approval.status_code == 200

    with SessionLocal() as session:
        rows = session.query(AuditEvent).order_by(
            AuditEvent.id.asc()
        ).all()
        assert len(rows) == 3
        middle_id = rows[1].id
        session.execute(
            delete(AuditEvent).where(
                AuditEvent.id == middle_id
            )
        )
        session.commit()

    integrity = client.get(
        "/v1/audit/integrity",
        headers=auth(),
    )
    assert integrity.status_code == 200
    data = integrity.json()
    assert data["valid"] is False
    assert data["reason"] == "previous_hash_mismatch"



def test_hash_key_tampering_is_detected() -> None:
    create_job_with_audit()

    with SessionLocal() as session:
        first = session.query(AuditEvent).order_by(
            AuditEvent.id.asc()
        ).first()
        assert first is not None
        session.execute(
            update(AuditEvent)
            .where(AuditEvent.id == first.id)
            .values(hash_key_id="unknown-key")
        )
        session.commit()

    integrity = client.get(
        "/v1/audit/integrity",
        headers=auth(),
    )
    assert integrity.status_code == 200
    assert integrity.json()["valid"] is False
    assert integrity.json()["reason"] == "hash_key_unavailable"
