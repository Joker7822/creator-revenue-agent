from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.db import (
    ChangeSetRecord,
    ExperimentRecord,
    ExperimentResultReviewRecord,
    ProductRecord,
    PublicationRecord,
    RolloutRecord,
)
from api_server.repository import add_audit
from api_server.schemas import (
    ChangeSetResponse,
    RolloutResponse,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _change_set_response(
    record: ChangeSetRecord,
) -> ChangeSetResponse:
    return ChangeSetResponse(
        change_set_id=record.id,
        review_id=record.review_id,
        experiment_id=record.experiment_id,
        product_id=record.product_id,
        change_type=record.change_type,
        status=record.status,
        expected=json.loads(record.expected_json),
        proposed=json.loads(record.proposed_json),
        created_by=record.created_by,
        approver=record.approver,
        approval_reason=record.approval_reason,
        created_at=record.created_at,
        decided_at=record.decided_at,
    )


def _rollout_response(
    record: RolloutRecord,
) -> RolloutResponse:
    return RolloutResponse(
        rollout_id=record.id,
        change_set_id=record.change_set_id,
        status=record.status,
        actor=record.actor,
        before=json.loads(record.before_json),
        after=json.loads(record.after_json),
        applied_at=record.applied_at,
    )


def _validated_price_plan(
    *,
    experiment: ExperimentRecord,
    product: ProductRecord,
) -> tuple[dict, dict]:
    plan = json.loads(experiment.plan_json)
    if plan.get("type") != "price_test":
        raise HTTPException(
            status_code=409,
            detail="only price-test rollouts are supported",
        )

    try:
        control_price = int(
            plan["control"]["price_minor_units"]
        )
        variant_price = int(
            plan["variant"]["price_minor_units"]
        )
        currency = str(plan["currency"]).upper()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=409,
            detail="invalid price experiment plan",
        )

    if control_price <= 0 or variant_price <= 0:
        raise HTTPException(
            status_code=409,
            detail="invalid price experiment values",
        )
    if currency != product.currency:
        raise HTTPException(
            status_code=409,
            detail="experiment currency does not match product",
        )

    change_ratio = abs(
        variant_price - control_price
    ) / control_price
    if change_ratio > 0.1000001:
        raise HTTPException(
            status_code=409,
            detail="price change exceeds 10 percent safety bound",
        )

    expected = {
        "currency": currency,
        "price_minor_units": control_price,
    }
    proposed = {
        "currency": currency,
        "price_minor_units": variant_price,
    }
    return expected, proposed


def create_change_set(
    session: Session,
    *,
    review_id: str,
    created_by: str,
) -> ChangeSetResponse:
    review = session.get(
        ExperimentResultReviewRecord,
        review_id,
    )
    if review is None:
        raise HTTPException(
            status_code=404,
            detail="experiment review not found",
        )
    if review.decision != "variant_preferred":
        raise HTTPException(
            status_code=409,
            detail="variant_preferred review required",
        )

    existing = session.scalar(
        select(ChangeSetRecord).where(
            ChangeSetRecord.review_id == review_id
        )
    )
    if existing is not None:
        return _change_set_response(existing)

    experiment = session.get(
        ExperimentRecord,
        review.experiment_id,
    )
    if experiment is None or experiment.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="completed experiment required",
        )

    product = session.get(
        ProductRecord,
        experiment.product_id,
    )
    if product is None or not product.active:
        raise HTTPException(
            status_code=409,
            detail="active product required",
        )

    expected, proposed = _validated_price_plan(
        experiment=experiment,
        product=product,
    )
    if product.price_minor_units != expected[
        "price_minor_units"
    ]:
        raise HTTPException(
            status_code=409,
            detail="production state no longer matches experiment control",
        )

    record = ChangeSetRecord(
        id=f"chg_{uuid4().hex}",
        review_id=review_id,
        experiment_id=experiment.id,
        product_id=product.id,
        change_type="product_price",
        status="pending_approval",
        expected_json=json.dumps(
            expected,
            separators=(",", ":"),
            sort_keys=True,
        ),
        proposed_json=json.dumps(
            proposed,
            separators=(",", ":"),
            sort_keys=True,
        ),
        created_by=created_by,
    )
    session.add(record)

    publication = session.get(
        PublicationRecord,
        experiment.publication_id,
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="change_set_created",
        actor=created_by,
        payload={
            "change_set_id": record.id,
            "review_id": review_id,
            "change_type": record.change_type,
            "expected": expected,
            "proposed": proposed,
        },
    )
    session.commit()
    session.refresh(record)
    return _change_set_response(record)


def get_change_set(
    session: Session,
    change_set_id: str,
) -> ChangeSetResponse:
    record = session.get(ChangeSetRecord, change_set_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="change set not found",
        )
    return _change_set_response(record)


def decide_change_set(
    session: Session,
    *,
    change_set_id: str,
    decision: str,
    actor: str,
    reason: str | None,
) -> ChangeSetResponse:
    record = session.get(ChangeSetRecord, change_set_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="change set not found",
        )

    if record.status != "pending_approval":
        if record.status == decision:
            return _change_set_response(record)
        raise HTTPException(
            status_code=409,
            detail=f"change set already {record.status}",
        )

    review = session.get(
        ExperimentResultReviewRecord,
        record.review_id,
    )
    if review is None:
        raise HTTPException(
            status_code=409,
            detail="experiment review missing",
        )

    if actor in {review.reviewer, record.created_by}:
        raise HTTPException(
            status_code=409,
            detail="separation of duties required",
        )

    record.status = decision
    record.approver = actor
    record.approval_reason = reason
    record.decided_at = utcnow()

    experiment = session.get(
        ExperimentRecord,
        record.experiment_id,
    )
    publication = (
        session.get(
            PublicationRecord,
            experiment.publication_id,
        )
        if experiment
        else None
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type=f"change_set_{decision}",
        actor=actor,
        payload={
            "change_set_id": record.id,
            "reason": reason,
        },
    )
    session.commit()
    session.refresh(record)
    return _change_set_response(record)


def apply_change_set(
    session: Session,
    *,
    change_set_id: str,
    actor: str,
) -> RolloutResponse:
    record = session.get(ChangeSetRecord, change_set_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="change set not found",
        )

    existing = session.scalar(
        select(RolloutRecord).where(
            RolloutRecord.change_set_id == change_set_id
        )
    )
    if existing is not None:
        return _rollout_response(existing)

    if record.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="approved change set required",
        )

    review = session.get(
        ExperimentResultReviewRecord,
        record.review_id,
    )
    if (
        review is None
        or review.decision != "variant_preferred"
    ):
        raise HTTPException(
            status_code=409,
            detail="variant_preferred review required",
        )

    experiment = session.get(
        ExperimentRecord,
        record.experiment_id,
    )
    if experiment is None or experiment.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="completed experiment required",
        )

    product = session.get(ProductRecord, record.product_id)
    if product is None or not product.active:
        raise HTTPException(
            status_code=409,
            detail="active product required",
        )

    expected = json.loads(record.expected_json)
    proposed = json.loads(record.proposed_json)
    _validated_price_plan(
        experiment=experiment,
        product=product,
    )

    before = {
        "currency": product.currency,
        "price_minor_units": product.price_minor_units,
    }
    if before != expected:
        raise HTTPException(
            status_code=409,
            detail="production state changed since change set creation",
        )

    after = {
        "currency": product.currency,
        "price_minor_units": int(
            proposed["price_minor_units"]
        ),
    }
    product.price_minor_units = after["price_minor_units"]

    rollout = RolloutRecord(
        id=f"roll_{uuid4().hex}",
        change_set_id=record.id,
        status="applied",
        actor=actor,
        before_json=json.dumps(
            before,
            separators=(",", ":"),
            sort_keys=True,
        ),
        after_json=json.dumps(
            after,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    session.add(rollout)
    record.status = "applied"

    publication = session.get(
        PublicationRecord,
        experiment.publication_id,
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="rollout_applied",
        actor=actor,
        payload={
            "rollout_id": rollout.id,
            "change_set_id": record.id,
            "before": before,
            "after": after,
        },
    )

    session.commit()
    session.refresh(rollout)
    return _rollout_response(rollout)


def get_rollout(
    session: Session,
    rollout_id: str,
) -> RolloutResponse:
    record = session.get(RolloutRecord, rollout_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="rollout not found",
        )
    return _rollout_response(record)
