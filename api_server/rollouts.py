from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.db import (
    AnalyticsEventRecord,
    ChangeSetRecord,
    ExperimentRecord,
    ExperimentResultReviewRecord,
    ProductRecord,
    PublicationRecord,
    RollbackRecord,
    RolloutRecord,
    TransactionRecord,
)
from api_server.repository import add_audit
from api_server.schemas import (
    ChangeSetResponse,
    RollbackResponse,
    RolloutMonitorCurrencySummary,
    RolloutMonitorResponse,
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



def _rollback_response(
    record: RollbackRecord,
) -> RollbackResponse:
    return RollbackResponse(
        rollback_id=record.id,
        rollout_id=record.rollout_id,
        actor=record.actor,
        reason=record.reason,
        before=json.loads(record.before_json),
        after=json.loads(record.after_json),
        rolled_back_at=record.rolled_back_at,
    )


def monitor_rollout(
    session: Session,
    *,
    rollout_id: str,
) -> RolloutMonitorResponse:
    rollout = session.get(RolloutRecord, rollout_id)
    if rollout is None:
        raise HTTPException(
            status_code=404,
            detail="rollout not found",
        )

    change_set = session.get(
        ChangeSetRecord,
        rollout.change_set_id,
    )
    if change_set is None:
        raise HTTPException(
            status_code=409,
            detail="change set missing",
        )

    experiment = session.get(
        ExperimentRecord,
        change_set.experiment_id,
    )
    if experiment is None:
        raise HTTPException(
            status_code=409,
            detail="experiment missing",
        )

    product = session.get(
        ProductRecord,
        change_set.product_id,
    )
    if product is None:
        raise HTTPException(
            status_code=409,
            detail="product missing",
        )

    rollback = session.scalar(
        select(RollbackRecord).where(
            RollbackRecord.rollout_id == rollout_id
        )
    )

    rollout_before = json.loads(rollout.before_json)
    rollout_after = json.loads(rollout.after_json)
    expected_state = (
        rollout_before
        if rollback is not None
        else rollout_after
    )
    current_state = {
        "currency": product.currency,
        "price_minor_units": product.price_minor_units,
    }
    monitoring_status = (
        "state_consistent"
        if current_state == expected_state
        else "state_drift"
    )

    publication_id = experiment.publication_id
    event_statement = select(AnalyticsEventRecord).where(
        AnalyticsEventRecord.publication_id == publication_id,
        AnalyticsEventRecord.occurred_at >= rollout.applied_at,
    )
    transaction_statement = select(TransactionRecord).where(
        TransactionRecord.product_id == product.id,
        TransactionRecord.occurred_at >= rollout.applied_at,
    )

    metrics_window_end = None
    if rollback is not None:
        metrics_window_end = rollback.rolled_back_at
        event_statement = event_statement.where(
            AnalyticsEventRecord.occurred_at
            <= rollback.rolled_back_at
        )
        transaction_statement = transaction_statement.where(
            TransactionRecord.occurred_at
            <= rollback.rolled_back_at
        )

    events = session.scalars(event_statement).all()
    transactions = session.scalars(
        transaction_statement
    ).all()

    impressions = sum(
        1
        for row in events
        if row.event_type == "impression"
    )
    clicks = sum(
        1
        for row in events
        if row.event_type == "click"
    )

    purchases = 0
    refunds = 0
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "sales_minor_units": 0,
            "refunds_minor_units": 0,
        }
    )
    for transaction in transactions:
        bucket = totals[transaction.currency]
        if transaction.kind == "sale":
            purchases += 1
            bucket["sales_minor_units"] += (
                transaction.amount_minor_units
            )
        elif transaction.kind == "refund":
            refunds += 1
            bucket["refunds_minor_units"] += (
                transaction.amount_minor_units
            )

    currencies = [
        RolloutMonitorCurrencySummary(
            currency=currency,
            sales_minor_units=values[
                "sales_minor_units"
            ],
            refunds_minor_units=values[
                "refunds_minor_units"
            ],
            net_revenue_minor_units=(
                values["sales_minor_units"]
                - values["refunds_minor_units"]
            ),
        )
        for currency, values in sorted(totals.items())
    ]

    return RolloutMonitorResponse(
        rollout_id=rollout.id,
        rollout_status=rollout.status,
        monitoring_status=monitoring_status,
        expected_state=expected_state,
        current_state=current_state,
        metrics_window_start=rollout.applied_at,
        metrics_window_end=metrics_window_end,
        impressions=impressions,
        clicks=clicks,
        purchases=purchases,
        refunds=refunds,
        ctr=(clicks / impressions) if impressions else 0.0,
        cvr=(purchases / clicks) if clicks else 0.0,
        currencies=currencies,
    )


def rollback_rollout(
    session: Session,
    *,
    rollout_id: str,
    actor: str,
    reason: str,
) -> RollbackResponse:
    existing = session.scalar(
        select(RollbackRecord).where(
            RollbackRecord.rollout_id == rollout_id
        )
    )
    if existing is not None:
        return _rollback_response(existing)

    rollout = session.get(RolloutRecord, rollout_id)
    if rollout is None:
        raise HTTPException(
            status_code=404,
            detail="rollout not found",
        )
    if rollout.status != "applied":
        raise HTTPException(
            status_code=409,
            detail="applied rollout required",
        )

    change_set = session.get(
        ChangeSetRecord,
        rollout.change_set_id,
    )
    if change_set is None:
        raise HTTPException(
            status_code=409,
            detail="change set missing",
        )
    if change_set.change_type != "product_price":
        raise HTTPException(
            status_code=409,
            detail="unsupported rollback change type",
        )

    experiment = session.get(
        ExperimentRecord,
        change_set.experiment_id,
    )
    if experiment is None:
        raise HTTPException(
            status_code=409,
            detail="experiment missing",
        )

    product = session.get(
        ProductRecord,
        change_set.product_id,
    )
    if product is None or not product.active:
        raise HTTPException(
            status_code=409,
            detail="active product required",
        )

    expected_current = json.loads(rollout.after_json)
    restore_state = json.loads(rollout.before_json)
    current_state = {
        "currency": product.currency,
        "price_minor_units": product.price_minor_units,
    }

    if current_state != expected_current:
        raise HTTPException(
            status_code=409,
            detail="production state changed since rollout",
        )

    if restore_state.get("currency") != product.currency:
        raise HTTPException(
            status_code=409,
            detail="rollback currency mismatch",
        )

    product.price_minor_units = int(
        restore_state["price_minor_units"]
    )

    rollback = RollbackRecord(
        id=f"rb_{uuid4().hex}",
        rollout_id=rollout.id,
        actor=actor,
        reason=reason,
        before_json=json.dumps(
            current_state,
            separators=(",", ":"),
            sort_keys=True,
        ),
        after_json=json.dumps(
            restore_state,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    session.add(rollback)
    rollout.status = "rolled_back"
    change_set.status = "rolled_back"

    publication = session.get(
        PublicationRecord,
        experiment.publication_id,
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="rollout_rolled_back",
        actor=actor,
        payload={
            "rollback_id": rollback.id,
            "rollout_id": rollout.id,
            "change_set_id": change_set.id,
            "reason": reason,
            "before": current_state,
            "after": restore_state,
        },
    )

    session.commit()
    session.refresh(rollback)
    return _rollback_response(rollback)


def get_rollback(
    session: Session,
    rollback_id: str,
) -> RollbackResponse:
    record = session.get(RollbackRecord, rollback_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="rollback not found",
        )
    return _rollback_response(record)
