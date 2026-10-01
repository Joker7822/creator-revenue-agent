from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.db import (
    ExperimentRecord,
    OptimizationProposalRecord,
    ProductRecord,
    PublicationRecord,
)
from api_server.repository import add_audit
from api_server.schemas import ExperimentResponse


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
