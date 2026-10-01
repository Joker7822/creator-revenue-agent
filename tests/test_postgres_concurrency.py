import threading

import pytest

from api_server.db import (
    AuditChainState,
    SessionLocal,
    engine,
    production_database_locking_status,
)
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
