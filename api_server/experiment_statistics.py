from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.db import (
    ExperimentAssignmentRecord,
    ExperimentEventRecord,
    ExperimentRecord,
    ExperimentResultReviewRecord,
    ExperimentTransactionLinkRecord,
    PublicationRecord,
    TransactionRecord,
)
from api_server.repository import add_audit
from api_server.schemas import (
    ExperimentCurrencyResult,
    ExperimentReadinessGates,
    ExperimentResultReviewResponse,
    ExperimentStatisticalArm,
    ExperimentStatisticsResponse,
    ProportionStatistic,
)


Z_95 = 1.959963984540054


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _wilson(successes: int, trials: int) -> ProportionStatistic:
    if trials <= 0 or successes < 0 or successes > trials:
        return ProportionStatistic(
            numerator=successes,
            denominator=trials,
            rate=None,
            ci_lower=None,
            ci_upper=None,
        )

    rate = successes / trials
    z2 = Z_95 * Z_95
    denominator = 1.0 + z2 / trials
    center = (rate + z2 / (2.0 * trials)) / denominator
    margin = (
        Z_95
        * math.sqrt(
            (rate * (1.0 - rate) / trials)
            + (z2 / (4.0 * trials * trials))
        )
        / denominator
    )

    return ProportionStatistic(
        numerator=successes,
        denominator=trials,
        rate=rate,
        ci_lower=max(0.0, center - margin),
        ci_upper=min(1.0, center + margin),
    )


def _two_proportion_p_value(
    successes_a: int,
    trials_a: int,
    successes_b: int,
    trials_b: int,
) -> float | None:
    if (
        trials_a <= 0
        or trials_b <= 0
        or successes_a < 0
        or successes_b < 0
        or successes_a > trials_a
        or successes_b > trials_b
    ):
        return None

    rate_a = successes_a / trials_a
    rate_b = successes_b / trials_b
    pooled = (successes_a + successes_b) / (trials_a + trials_b)
    variance = pooled * (1.0 - pooled) * (
        (1.0 / trials_a) + (1.0 / trials_b)
    )

    if variance <= 0.0:
        return 1.0 if rate_a == rate_b else 0.0

    z = (rate_b - rate_a) / math.sqrt(variance)
    return math.erfc(abs(z) / math.sqrt(2.0))


def _arm(
    *,
    arm: str,
    assignments: list[ExperimentAssignmentRecord],
    events: list[ExperimentEventRecord],
    transaction_rows: list[tuple[
        ExperimentTransactionLinkRecord,
        TransactionRecord,
    ]],
) -> ExperimentStatisticalArm:
    arm_assignments = sum(
        1 for row in assignments if row.arm == arm
    )
    impressions = sum(
        1 for row in events
        if row.arm == arm and row.event_type == "impression"
    )
    clicks = sum(
        1 for row in events
        if row.arm == arm and row.event_type == "click"
    )

    purchases = 0
    refunds = 0
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "sales_minor_units": 0,
            "refunds_minor_units": 0,
        }
    )

    for link, transaction in transaction_rows:
        if link.arm != arm:
            continue
        bucket = totals[transaction.currency]
        if transaction.kind == "sale":
            purchases += 1
            bucket["sales_minor_units"] += transaction.amount_minor_units
        elif transaction.kind == "refund":
            refunds += 1
            bucket["refunds_minor_units"] += transaction.amount_minor_units

    currencies = [
        ExperimentCurrencyResult(
            currency=currency,
            sales_minor_units=values["sales_minor_units"],
            refunds_minor_units=values["refunds_minor_units"],
            net_revenue_minor_units=(
                values["sales_minor_units"]
                - values["refunds_minor_units"]
            ),
        )
        for currency, values in sorted(totals.items())
    ]

    return ExperimentStatisticalArm(
        arm=arm,
        assignments=arm_assignments,
        impressions=impressions,
        clicks=clicks,
        purchases=purchases,
        refunds=refunds,
        ctr=_wilson(clicks, impressions),
        cvr=_wilson(purchases, clicks),
        currencies=currencies,
    )


def evaluate_experiment_statistics(
    session: Session,
    *,
    experiment_id: str,
) -> ExperimentStatisticsResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")

    assignments = list(
        session.scalars(
            select(ExperimentAssignmentRecord).where(
                ExperimentAssignmentRecord.experiment_id == experiment_id
            )
        ).all()
    )
    events = list(
        session.scalars(
            select(ExperimentEventRecord).where(
                ExperimentEventRecord.experiment_id == experiment_id
            )
        ).all()
    )
    transaction_rows = list(
        session.execute(
            select(
                ExperimentTransactionLinkRecord,
                TransactionRecord,
            )
            .join(
                TransactionRecord,
                ExperimentTransactionLinkRecord.transaction_id
                == TransactionRecord.id,
            )
            .where(
                ExperimentTransactionLinkRecord.experiment_id
                == experiment_id
            )
        ).all()
    )

    control = _arm(
        arm="control",
        assignments=assignments,
        events=events,
        transaction_rows=transaction_rows,
    )
    variant = _arm(
        arm="variant",
        assignments=assignments,
        events=events,
        transaction_rows=transaction_rows,
    )

    min_runtime_hours = _env_int("EXPERIMENT_MIN_RUNTIME_HOURS", 24)
    min_assignments = _env_int(
        "EXPERIMENT_MIN_ASSIGNMENTS_PER_ARM",
        100,
    )
    min_impressions = _env_int(
        "EXPERIMENT_MIN_IMPRESSIONS_PER_ARM",
        100,
    )
    min_clicks = _env_int(
        "EXPERIMENT_MIN_CLICKS_PER_ARM",
        20,
    )

    started_at = _aware(experiment.started_at)
    runtime_hours = 0.0
    if started_at is not None:
        runtime_hours = max(
            0.0,
            (utcnow() - started_at).total_seconds() / 3600.0,
        )

    runtime_passed = (
        started_at is not None
        and runtime_hours >= min_runtime_hours
    )
    assignments_passed = (
        min(control.assignments, variant.assignments)
        >= min_assignments
    )
    impressions_passed = (
        min(control.impressions, variant.impressions)
        >= min_impressions
    )
    clicks_passed = (
        min(control.clicks, variant.clicks)
        >= min_clicks
    )

    gates = ExperimentReadinessGates(
        min_runtime_hours=min_runtime_hours,
        runtime_hours=runtime_hours,
        runtime_passed=runtime_passed,
        min_assignments_per_arm=min_assignments,
        assignments_passed=assignments_passed,
        min_impressions_per_arm=min_impressions,
        impressions_passed=impressions_passed,
        min_clicks_per_arm=min_clicks,
        clicks_passed=clicks_passed,
        all_passed=(
            runtime_passed
            and assignments_passed
            and impressions_passed
            and clicks_passed
        ),
    )

    return ExperimentStatisticsResponse(
        experiment_id=experiment_id,
        status=experiment.status,
        confidence_level=0.95,
        alpha=0.05,
        gates=gates,
        control=control,
        variant=variant,
        tests={
            "ctr_two_sided_p_value": _two_proportion_p_value(
                control.clicks,
                control.impressions,
                variant.clicks,
                variant.impressions,
            ),
            "cvr_two_sided_p_value": _two_proportion_p_value(
                control.purchases,
                control.clicks,
                variant.purchases,
                variant.clicks,
            ),
        },
        decision="manual_review_required",
        winner=None,
    )


def _review_response(
    record: ExperimentResultReviewRecord,
) -> ExperimentResultReviewResponse:
    return ExperimentResultReviewResponse(
        review_id=record.id,
        experiment_id=record.experiment_id,
        decision=record.decision,
        reviewer=record.reviewer,
        reason=record.reason,
        statistics_snapshot=json.loads(record.statistics_json),
        created_at=record.created_at,
    )


def create_experiment_review(
    session: Session,
    *,
    experiment_id: str,
    decision: str,
    reviewer: str,
    reason: str | None,
) -> ExperimentResultReviewResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if experiment.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="completed experiment required",
        )

    statistics = evaluate_experiment_statistics(
        session,
        experiment_id=experiment_id,
    )
    if not statistics.gates.all_passed:
        raise HTTPException(
            status_code=409,
            detail="statistical readiness gates not met",
        )

    existing = session.scalar(
        select(ExperimentResultReviewRecord).where(
            ExperimentResultReviewRecord.experiment_id == experiment_id
        )
    )
    if existing is not None:
        same = (
            existing.decision == decision
            and existing.reviewer == reviewer
            and existing.reason == reason
        )
        if not same:
            raise HTTPException(
                status_code=409,
                detail="experiment review already recorded",
            )
        return _review_response(existing)

    review = ExperimentResultReviewRecord(
        id=f"rev_{uuid4().hex}",
        experiment_id=experiment_id,
        decision=decision,
        reviewer=reviewer,
        reason=reason,
        statistics_json=json.dumps(
            statistics.model_dump(mode="json"),
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    session.add(review)

    publication = session.get(
        PublicationRecord,
        experiment.publication_id,
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="experiment_review_recorded",
        actor=reviewer,
        payload={
            "experiment_id": experiment_id,
            "review_id": review.id,
            "decision": decision,
            "reason": reason,
        },
    )
    session.commit()
    session.refresh(review)
    return _review_response(review)


def get_experiment_review(
    session: Session,
    *,
    experiment_id: str,
) -> ExperimentResultReviewResponse:
    review = session.scalar(
        select(ExperimentResultReviewRecord).where(
            ExperimentResultReviewRecord.experiment_id == experiment_id
        )
    )
    if review is None:
        raise HTTPException(
            status_code=404,
            detail="experiment review not found",
        )
    return _review_response(review)
