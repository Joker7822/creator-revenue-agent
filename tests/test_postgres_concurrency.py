import threading

import pytest
from fastapi import HTTPException

from api_server.db import (
    AuditChainState,
    JobRecord,
    ProductRecord,
    PublicationRecord,
    SessionLocal,
    TransactionRecord,
    engine,
    production_database_locking_status,
)
from api_server.repository import record_transaction
from api_server.state_machine import lock_row


pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason="requires PostgreSQL row locking",
)


def test_postgres_readiness_recognizes_row_locking(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "PRODUCTION_REQUIRE_ROW_LOCKING_DATABASE",
        "true",
    )
    ready, detail = production_database_locking_status()
    assert ready is True
    assert "dialect=postgresql" in detail
    assert "row_locking=True" in detail


def test_postgres_for_update_serializes_competing_writer() -> None:
    with SessionLocal() as session:
        session.add(
            AuditChainState(
                id=1,
                last_event_id=None,
                last_hash="0" * 64,
                hash_key_id="test-audit-2026-10",
                state_hash="1" * 64,
            )
        )
        session.commit()

    first_locked = threading.Event()
    second_started = threading.Event()
    second_acquired = threading.Event()
    release_first = threading.Event()
    errors: list[BaseException] = []

    def first_writer() -> None:
        try:
            with SessionLocal() as session:
                row = lock_row(
                    session,
                    AuditChainState,
                    AuditChainState.id,
                    1,
                )
                assert row is not None
                first_locked.set()
                assert release_first.wait(timeout=5)
                row.last_hash = "2" * 64
                session.commit()
        except BaseException as exc:
            errors.append(exc)
            first_locked.set()

    def second_writer() -> None:
        try:
            assert first_locked.wait(timeout=5)
            with SessionLocal() as session:
                second_started.set()
                row = lock_row(
                    session,
                    AuditChainState,
                    AuditChainState.id,
                    1,
                )
                assert row is not None
                second_acquired.set()
                assert row.last_hash == "2" * 64
                row.last_hash = "3" * 64
                session.commit()
        except BaseException as exc:
            errors.append(exc)
            second_acquired.set()

    first = threading.Thread(target=first_writer)
    second = threading.Thread(target=second_writer)
    first.start()
    assert first_locked.wait(timeout=5)
    second.start()
    assert second_started.wait(timeout=5)

    assert second_acquired.wait(timeout=0.25) is False

    release_first.set()
    assert second_acquired.wait(timeout=5)

    first.join(timeout=5)
    second.join(timeout=5)
    assert first.is_alive() is False
    assert second.is_alive() is False
    assert errors == []

    with SessionLocal() as session:
        row = session.get(AuditChainState, 1)
        assert row is not None
        assert row.last_hash == "3" * 64



def test_concurrent_refunds_never_exceed_original_sale() -> None:
    with SessionLocal() as session:
        session.add(
            JobRecord(
                id="job_refund_race",
                campaign_type="members_only_release",
                target_segment="subscribers",
                title="Refund race",
                teaser="Refund race",
                price_cents=1500,
                creator_age=21,
                age_verified=True,
                consent_verified=True,
                depicts_real_person=False,
                real_person_consent_verified=False,
                policy_allowed=True,
            )
        )
        session.flush()
        session.add(
            PublicationRecord(
                id="pub_refund_race",
                job_id="job_refund_race",
                status="published",
                destination="internal",
                publisher="test",
            )
        )
        session.flush()
        session.add(
            ProductRecord(
                id="prod_refund_race",
                publication_id="pub_refund_race",
                name="Refund race product",
                currency="JPY",
                price_minor_units=1500,
                active=True,
            )
        )
        session.flush()
        session.add(
            TransactionRecord(
                id="sale_refund_race",
                product_id="prod_refund_race",
                kind="sale",
                original_sale_id=None,
                amount_minor_units=1500,
                currency="JPY",
            )
        )
        session.commit()

    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[BaseException] = []

    def refund(transaction_id: str) -> None:
        try:
            barrier.wait(timeout=5)
            with SessionLocal() as session:
                try:
                    record_transaction(
                        session,
                        transaction_id=transaction_id,
                        product_id="prod_refund_race",
                        kind="refund",
                        original_sale_id="sale_refund_race",
                        amount_minor_units=1000,
                        currency="JPY",
                        occurred_at=None,
                    )
                    results.append(200)
                except HTTPException as exc:
                    results.append(exc.status_code)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(
        target=refund,
        args=("refund_race_1",),
    )
    second = threading.Thread(
        target=refund,
        args=("refund_race_2",),
    )
    first.start()
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert first.is_alive() is False
    assert second.is_alive() is False
    assert errors == []
    assert sorted(results) == [200, 409]

    with SessionLocal() as session:
        refunds = session.query(TransactionRecord).filter(
            TransactionRecord.kind == "refund",
            TransactionRecord.original_sale_id
            == "sale_refund_race",
        ).all()
        assert len(refunds) == 1
        assert refunds[0].amount_minor_units == 1000
