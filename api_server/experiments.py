from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.db import (
    ExperimentAssignmentRecord,
    ExperimentEventRecord,
    ExperimentRecord,
    ExperimentTransactionLinkRecord,
    OptimizationProposalRecord,
    ProductRecord,
    PublicationRecord,
    TransactionRecord,
)
from api_server.repository import add_audit
from api_server.schemas import (
    ExperimentArmResult,
    ExperimentAssignmentResponse,
    ExperimentCurrencyResult,
    ExperimentEventResponse,
    ExperimentResponse,
    ExperimentResultsResponse,
    ExperimentTransactionLinkResponse,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _response(record: ExperimentRecord) -> ExperimentResponse:
    return ExperimentResponse(
        experiment_id=record.id,
        proposal_id=record.proposal_id,
        publication_id=record.publication_id,
        product_id=record.product_id,
        recommendation_index=record.recommendation_index,
        status=record.status,
        plan=json.loads(record.plan_json),
        owner=record.owner,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        outcome=json.loads(record.outcome_json)
        if record.outcome_json
        else None,
    )


def _build_plan(
    *,
    recommendation: dict[str, Any],
    product: ProductRecord,
) -> dict[str, Any]:
    rec_type = recommendation.get("type")
    action = recommendation.get("action")

    if rec_type == "price_test":
        return {
            "type": "price_test",
            "action": action,
            "currency": product.currency,
            "control": {
                "price_minor_units": product.price_minor_units,
            },
            "variant": {
                "price_minor_units": recommendation[
                    "candidate_price_minor_units"
                ],
            },
            "allocation": {
                "control_percent": 50,
                "variant_percent": 50,
            },
            "automatic_application": False,
        }

    if rec_type == "creative_test":
        return {
            "type": "creative_test",
            "action": action,
            "control": {
                "teaser": "current_non_explicit_teaser",
            },
            "variant": {
                "teaser": "alternative_non_explicit_teaser",
            },
            "allocation": {
                "control_percent": 50,
                "variant_percent": 50,
            },
            "automatic_application": False,
        }

    if rec_type == "timing_test":
        return {
            "type": "timing_test",
            "action": action,
            "control": {
                "schedule": "current_schedule",
            },
            "variant": {
                "schedule": "alternate_schedule",
            },
            "allocation": {
                "control_percent": 50,
                "variant_percent": 50,
            },
            "automatic_application": False,
        }

    raise HTTPException(
        status_code=409,
        detail="recommendation is not experimentable",
    )


def create_experiment(
    session: Session,
    *,
    proposal_id: str,
    recommendation_index: int,
    owner: str,
) -> ExperimentResponse:
    proposal = session.get(OptimizationProposalRecord, proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail="optimization proposal not found",
        )
    if proposal.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="approved optimization proposal required",
        )

    existing = session.scalar(
        select(ExperimentRecord).where(
            ExperimentRecord.proposal_id == proposal_id,
            ExperimentRecord.recommendation_index
            == recommendation_index,
        )
    )
    if existing is not None:
        return _response(existing)

    recommendations = json.loads(proposal.recommendations_json)
    if recommendation_index >= len(recommendations):
        raise HTTPException(
            status_code=400,
            detail="recommendation index out of range",
        )

    product = session.get(ProductRecord, proposal.product_id)
    if product is None or not product.active:
        raise HTTPException(
            status_code=409,
            detail="active product required",
        )

    recommendation = recommendations[recommendation_index]
    plan = _build_plan(
        recommendation=recommendation,
        product=product,
    )

    experiment = ExperimentRecord(
        id=f"exp_{uuid4().hex}",
        proposal_id=proposal_id,
        publication_id=proposal.publication_id,
        product_id=proposal.product_id,
        recommendation_index=recommendation_index,
        status="draft",
        plan_json=json.dumps(
            plan,
            separators=(",", ":"),
            sort_keys=True,
        ),
        owner=owner,
    )
    session.add(experiment)

    publication = session.get(
        PublicationRecord,
        proposal.publication_id,
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="experiment_created",
        actor=owner,
        payload={
            "experiment_id": experiment.id,
            "proposal_id": proposal_id,
            "recommendation_index": recommendation_index,
            "type": plan["type"],
        },
    )

    session.commit()
    session.refresh(experiment)
    return _response(experiment)


def get_experiment(
    session: Session,
    experiment_id: str,
) -> ExperimentResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=404,
            detail="experiment not found",
        )
    return _response(experiment)


def start_experiment(
    session: Session,
    *,
    experiment_id: str,
    actor: str,
) -> ExperimentResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=404,
            detail="experiment not found",
        )
    if experiment.status != "draft":
        if experiment.status == "running":
            return _response(experiment)
        raise HTTPException(
            status_code=409,
            detail=f"experiment already {experiment.status}",
        )

    experiment.status = "running"
    experiment.started_at = utcnow()

    publication = session.get(
        PublicationRecord,
        experiment.publication_id,
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="experiment_started",
        actor=actor,
        payload={
            "experiment_id": experiment.id,
            "automatic_application": False,
        },
    )
    session.commit()
    session.refresh(experiment)
    return _response(experiment)


def complete_experiment(
    session: Session,
    *,
    experiment_id: str,
    actor: str,
    outcome: dict[str, Any],
) -> ExperimentResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=404,
            detail="experiment not found",
        )
    if experiment.status != "running":
        if experiment.status == "completed":
            return _response(experiment)
        raise HTTPException(
            status_code=409,
            detail="running experiment required",
        )

    from api_server.experiment_statistics import (
        evaluate_experiment_statistics,
    )

    statistics = evaluate_experiment_statistics(
        session,
        experiment_id=experiment_id,
    )
    if not statistics.gates.all_passed:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "experiment not ready for completion",
                "gates": statistics.gates.model_dump(),
            },
        )

    experiment.status = "completed"
    experiment.completed_at = utcnow()
    experiment.outcome_json = json.dumps(
        outcome,
        separators=(",", ":"),
        sort_keys=True,
    )

    publication = session.get(
        PublicationRecord,
        experiment.publication_id,
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="experiment_completed",
        actor=actor,
        payload={
            "experiment_id": experiment.id,
            "outcome": outcome,
        },
    )
    session.commit()
    session.refresh(experiment)
    return _response(experiment)


def cancel_experiment(
    session: Session,
    *,
    experiment_id: str,
    actor: str,
    reason: str | None,
) -> ExperimentResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=404,
            detail="experiment not found",
        )
    if experiment.status == "cancelled":
        return _response(experiment)
    if experiment.status == "completed":
        raise HTTPException(
            status_code=409,
            detail="completed experiment cannot be cancelled",
        )

    experiment.status = "cancelled"
    experiment.completed_at = utcnow()
    experiment.outcome_json = json.dumps(
        {"cancel_reason": reason},
        separators=(",", ":"),
        sort_keys=True,
    )

    publication = session.get(
        PublicationRecord,
        experiment.publication_id,
    )
    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type="experiment_cancelled",
        actor=actor,
        payload={
            "experiment_id": experiment.id,
            "reason": reason,
        },
    )
    session.commit()
    session.refresh(experiment)
    return _response(experiment)



def _subject_hash(
    *,
    experiment_id: str,
    subject_key: str,
) -> str:
    payload = f"{experiment_id}\0{subject_key}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assign_subject(
    session: Session,
    *,
    experiment_id: str,
    subject_key: str,
) -> ExperimentAssignmentResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if experiment.status != "running":
        raise HTTPException(
            status_code=409,
            detail="running experiment required",
        )

    subject_hash = _subject_hash(
        experiment_id=experiment_id,
        subject_key=subject_key,
    )
    existing = session.scalar(
        select(ExperimentAssignmentRecord).where(
            ExperimentAssignmentRecord.experiment_id == experiment_id,
            ExperimentAssignmentRecord.subject_hash == subject_hash,
        )
    )
    if existing is not None:
        return ExperimentAssignmentResponse(
            assignment_id=existing.id,
            experiment_id=existing.experiment_id,
            arm=existing.arm,
            assigned_at=existing.assigned_at,
        )

    plan = json.loads(experiment.plan_json)
    allocation = plan.get("allocation", {})
    control_percent = int(allocation.get("control_percent", 50))
    if control_percent < 0 or control_percent > 100:
        raise HTTPException(
            status_code=500,
            detail="invalid experiment allocation",
        )

    bucket = int(subject_hash[:8], 16) % 100
    arm = "control" if bucket < control_percent else "variant"

    assignment = ExperimentAssignmentRecord(
        id=f"asn_{uuid4().hex}",
        experiment_id=experiment_id,
        subject_hash=subject_hash,
        arm=arm,
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)

    return ExperimentAssignmentResponse(
        assignment_id=assignment.id,
        experiment_id=assignment.experiment_id,
        arm=assignment.arm,
        assigned_at=assignment.assigned_at,
    )


def record_experiment_event(
    session: Session,
    *,
    experiment_id: str,
    event_id: str,
    assignment_id: str,
    event_type: str,
    occurred_at: datetime | None,
) -> ExperimentEventResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if experiment.status != "running":
        raise HTTPException(
            status_code=409,
            detail="running experiment required",
        )

    assignment = session.get(
        ExperimentAssignmentRecord,
        assignment_id,
    )
    if (
        assignment is None
        or assignment.experiment_id != experiment_id
    ):
        raise HTTPException(
            status_code=409,
            detail="assignment does not belong to experiment",
        )

    existing = session.get(ExperimentEventRecord, event_id)
    if existing is not None:
        same = (
            existing.experiment_id == experiment_id
            and existing.assignment_id == assignment_id
            and existing.event_type == event_type
        )
        if not same:
            raise HTTPException(
                status_code=409,
                detail="event idempotency conflict",
            )
        return ExperimentEventResponse(
            event_id=existing.id,
            experiment_id=existing.experiment_id,
            assignment_id=existing.assignment_id,
            arm=existing.arm,
            event_type=existing.event_type,
            occurred_at=existing.occurred_at,
            recorded_at=existing.recorded_at,
        )

    event = ExperimentEventRecord(
        id=event_id,
        experiment_id=experiment_id,
        assignment_id=assignment_id,
        arm=assignment.arm,
        event_type=event_type,
        occurred_at=occurred_at or utcnow(),
    )
    session.add(event)
    session.commit()
    session.refresh(event)

    return ExperimentEventResponse(
        event_id=event.id,
        experiment_id=event.experiment_id,
        assignment_id=event.assignment_id,
        arm=event.arm,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        recorded_at=event.recorded_at,
    )


def link_experiment_transaction(
    session: Session,
    *,
    experiment_id: str,
    transaction_id: str,
    assignment_id: str,
) -> ExperimentTransactionLinkResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")

    assignment = session.get(
        ExperimentAssignmentRecord,
        assignment_id,
    )
    if (
        assignment is None
        or assignment.experiment_id != experiment_id
    ):
        raise HTTPException(
            status_code=409,
            detail="assignment does not belong to experiment",
        )

    transaction = session.get(TransactionRecord, transaction_id)
    if transaction is None:
        raise HTTPException(
            status_code=404,
            detail="transaction not found",
        )
    if transaction.product_id != experiment.product_id:
        raise HTTPException(
            status_code=409,
            detail="transaction product does not match experiment",
        )

    existing = session.get(
        ExperimentTransactionLinkRecord,
        transaction_id,
    )
    if existing is not None:
        if (
            existing.experiment_id != experiment_id
            or existing.assignment_id != assignment_id
        ):
            raise HTTPException(
                status_code=409,
                detail="transaction already linked elsewhere",
            )
        return ExperimentTransactionLinkResponse(
            transaction_id=transaction.id,
            experiment_id=existing.experiment_id,
            assignment_id=existing.assignment_id,
            arm=existing.arm,
            kind=transaction.kind,
            amount_minor_units=transaction.amount_minor_units,
            currency=transaction.currency,
            linked_at=existing.linked_at,
        )

    link = ExperimentTransactionLinkRecord(
        transaction_id=transaction_id,
        experiment_id=experiment_id,
        assignment_id=assignment_id,
        arm=assignment.arm,
    )
    session.add(link)
    session.commit()
    session.refresh(link)

    return ExperimentTransactionLinkResponse(
        transaction_id=transaction.id,
        experiment_id=link.experiment_id,
        assignment_id=link.assignment_id,
        arm=link.arm,
        kind=transaction.kind,
        amount_minor_units=transaction.amount_minor_units,
        currency=transaction.currency,
        linked_at=link.linked_at,
    )


def _arm_result(
    *,
    arm: str,
    assignment_count: int,
    events: list[ExperimentEventRecord],
    transaction_rows: list[tuple[
        ExperimentTransactionLinkRecord,
        TransactionRecord,
    ]],
) -> ExperimentArmResult:
    impressions = sum(
        1 for event in events
        if event.arm == arm
        and event.event_type == "impression"
    )
    clicks = sum(
        1 for event in events
        if event.arm == arm
        and event.event_type == "click"
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

    return ExperimentArmResult(
        arm=arm,
        assignments=assignment_count,
        impressions=impressions,
        clicks=clicks,
        purchases=purchases,
        refunds=refunds,
        ctr=(clicks / impressions) if impressions else 0.0,
        cvr=(purchases / clicks) if clicks else 0.0,
        currencies=currencies,
    )


def get_experiment_results(
    session: Session,
    *,
    experiment_id: str,
) -> ExperimentResultsResponse:
    experiment = session.get(ExperimentRecord, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")

    assignments = session.scalars(
        select(ExperimentAssignmentRecord).where(
            ExperimentAssignmentRecord.experiment_id == experiment_id
        )
    ).all()
    events = session.scalars(
        select(ExperimentEventRecord).where(
            ExperimentEventRecord.experiment_id == experiment_id
        )
    ).all()
    transaction_rows = session.execute(
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

    control = _arm_result(
        arm="control",
        assignment_count=sum(
            1 for row in assignments if row.arm == "control"
        ),
        events=list(events),
        transaction_rows=list(transaction_rows),
    )
    variant = _arm_result(
        arm="variant",
        assignment_count=sum(
            1 for row in assignments if row.arm == "variant"
        ),
        events=list(events),
        transaction_rows=list(transaction_rows),
    )

    evaluation_status = (
        "ready_for_manual_review"
        if min(control.clicks, variant.clicks) >= 20
        else "insufficient_data"
    )

    currencies = sorted(
        {
            row.currency
            for row in control.currencies + variant.currencies
        }
    )
    control_net = {
        row.currency: row.net_revenue_minor_units
        for row in control.currencies
    }
    variant_net = {
        row.currency: row.net_revenue_minor_units
        for row in variant.currencies
    }

    comparison = {
        "ctr_delta_variant_minus_control": (
            variant.ctr - control.ctr
        ),
        "cvr_delta_variant_minus_control": (
            variant.cvr - control.cvr
        ),
        "net_revenue_delta_by_currency": {
            currency: (
                variant_net.get(currency, 0)
                - control_net.get(currency, 0)
            )
            for currency in currencies
        },
        "winner": None,
        "decision": "manual_review_required",
    }

    return ExperimentResultsResponse(
        experiment_id=experiment_id,
        status=experiment.status,
        evaluation_status=evaluation_status,
        control=control,
        variant=variant,
        comparison=comparison,
    )
