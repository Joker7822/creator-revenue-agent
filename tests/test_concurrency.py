import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from api_server.db import (
    ApprovalRecord,
    ProductRecord,
    SessionLocal,
)
from api_server.state_machine import commit_state_change


def test_optimistic_lock_rejects_stale_approval_writer() -> None:
    with SessionLocal() as session:
        record = ApprovalRecord(
            job_id="job_concurrency_approval",
            status="pending_review",
            required=True,
        )
        session.add(record)
        session.commit()
        assert record.state_version == 1

    first: Session = SessionLocal()
    second: Session = SessionLocal()
    try:
        first_row = first.get(
            ApprovalRecord,
            "job_concurrency_approval",
        )
        second_row = second.get(
            ApprovalRecord,
            "job_concurrency_approval",
        )
        assert first_row is not None
        assert second_row is not None
        assert first_row.state_version == 1
        assert second_row.state_version == 1

        first_row.status = "approved"
        commit_state_change(first)
        assert first_row.state_version == 2

        second_row.status = "rejected"
        with pytest.raises(HTTPException) as exc:
            commit_state_change(second)

        assert exc.value.status_code == 409
        assert exc.value.detail == (
            "concurrent state change detected"
        )
    finally:
        first.close()
        second.close()


def test_optimistic_lock_rejects_stale_product_writer() -> None:
    with SessionLocal() as session:
        product = ProductRecord(
            id="prod_concurrency",
            publication_id="pub_concurrency",
            name="Concurrent product",
            currency="JPY",
            price_minor_units=1500,
            active=True,
        )
        session.add(product)
        session.commit()
        assert product.state_version == 1

    first: Session = SessionLocal()
    second: Session = SessionLocal()
    try:
        first_row = first.get(
            ProductRecord,
            "prod_concurrency",
        )
        second_row = second.get(
            ProductRecord,
            "prod_concurrency",
        )
        assert first_row is not None
        assert second_row is not None

        first_row.price_minor_units = 1350
        commit_state_change(first)
        assert first_row.state_version == 2

        second_row.price_minor_units = 1400
        with pytest.raises(HTTPException) as exc:
            commit_state_change(second)

        assert exc.value.status_code == 409
    finally:
        first.close()
        second.close()
