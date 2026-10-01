from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api_server.db import (
    OptimizationProposalRecord,
    ProductRecord,
    PublicationRecord,
)
from api_server.repository import add_audit, get_metrics
from api_server.schemas import OptimizationProposalResponse


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _response(
    record: OptimizationProposalRecord,
) -> OptimizationProposalResponse:
    return OptimizationProposalResponse(
        proposal_id=record.id,
        publication_id=record.publication_id,
        product_id=record.product_id,
        window=record.window,
        status=record.status,
        metrics=json.loads(record.metrics_json),
        recommendations=json.loads(record.recommendations_json),
        reviewer=record.reviewer,
        reason=record.reason,
        created_at=record.created_at,
        decided_at=record.decided_at,
    )


def _recommendations(
    *,
    metrics: dict,
    product: ProductRecord,
) -> list[dict]:
    recommendations: list[dict] = []

    impressions = int(metrics["impressions"])
    clicks = int(metrics["clicks"])
    purchases = int(metrics["purchases"])
    refunds = int(metrics["refunds"])
    ctr = float(metrics["ctr"])
    cvr = float(metrics["cvr"])

    if impressions < 100:
        recommendations.append(
            {
                "type": "data_collection",
                "action": "collect_more_impressions",
                "reason": "sample_below_100_impressions",
                "target_impressions": 100,
            }
        )
    elif ctr < 0.05:
        recommendations.append(
            {
                "type": "creative_test",
                "action": "test_alternative_non_explicit_teaser",
                "reason": "ctr_below_5_percent",
                "guardrail": "metadata_only",
            }
        )

    if clicks < 20:
        recommendations.append(
            {
                "type": "data_collection",
                "action": "collect_more_clicks",
                "reason": "sample_below_20_clicks",
                "target_clicks": 20,
            }
        )
    elif cvr < 0.03 and product.price_minor_units > 1:
        candidate = max(1, round(product.price_minor_units * 0.90))
        recommendations.append(
            {
                "type": "price_test",
                "action": "test_lower_price",
                "reason": "cvr_below_3_percent",
                "currency": product.currency,
                "current_price_minor_units": product.price_minor_units,
                "candidate_price_minor_units": candidate,
                "max_change_percent": 10,
            }
        )
    elif cvr > 0.10 and purchases >= 5:
        candidate = max(
            product.price_minor_units + 1,
            round(product.price_minor_units * 1.10),
        )
        recommendations.append(
            {
                "type": "price_test",
                "action": "test_higher_price",
                "reason": "cvr_above_10_percent_with_5_plus_purchases",
                "currency": product.currency,
                "current_price_minor_units": product.price_minor_units,
                "candidate_price_minor_units": candidate,
                "max_change_percent": 10,
            }
        )

    if purchases >= 5 and refunds / purchases > 0.20:
        recommendations.append(
            {
                "type": "offer_review",
                "action": "review_offer_expectation_alignment",
                "reason": "refund_rate_above_20_percent",
            }
        )

    recommendations.append(
        {
            "type": "timing_test",
            "action": "run_controlled_posting_time_experiment",
            "reason": "no_time_of_day_winner_in_current_metrics",
            "guardrail": "proposal_only_no_auto_publish",
        }
    )

    return recommendations


def create_optimization_proposal(
    session: Session,
    *,
    publication_id: str,
    window: str,
) -> OptimizationProposalResponse:
    publication = session.get(PublicationRecord, publication_id)
    if publication is None or publication.status != "published":
        raise HTTPException(
            status_code=409,
            detail="published publication required",
        )

    product = session.scalar(
        select(ProductRecord)
        .where(
            ProductRecord.publication_id == publication_id,
            ProductRecord.active.is_(True),
        )
        .order_by(ProductRecord.created_at.asc())
    )
    if product is None:
        raise HTTPException(
            status_code=409,
            detail="active product required",
        )

    metrics_model = get_metrics(
        session,
        window=window,
        publication_id=publication_id,
    )
    metrics = metrics_model.model_dump(mode="json")
    recommendations = _recommendations(
        metrics=metrics,
        product=product,
    )

    proposal = OptimizationProposalRecord(
        id=f"opt_{uuid4().hex}",
        publication_id=publication_id,
        product_id=product.id,
        window=window,
        status="pending_review",
        metrics_json=json.dumps(
            metrics,
            separators=(",", ":"),
            sort_keys=True,
        ),
        recommendations_json=json.dumps(
            recommendations,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    session.add(proposal)
    add_audit(
        session,
        job_id=publication.job_id,
        event_type="optimizer_proposal_created",
        actor="optimizer",
        payload={
            "proposal_id": proposal.id,
            "publication_id": publication_id,
            "product_id": product.id,
            "window": window,
        },
    )
    session.commit()
    session.refresh(proposal)
    return _response(proposal)


def get_optimization_proposal(
    session: Session,
    proposal_id: str,
) -> OptimizationProposalResponse:
    proposal = session.get(OptimizationProposalRecord, proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail="optimization proposal not found",
        )
    return _response(proposal)


def decide_optimization_proposal(
    session: Session,
    *,
    proposal_id: str,
    decision: str,
    reviewer: str,
    reason: str | None,
) -> OptimizationProposalResponse:
    proposal = session.get(OptimizationProposalRecord, proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail="optimization proposal not found",
        )

    if proposal.status != "pending_review":
        if proposal.status == decision:
            return _response(proposal)
        raise HTTPException(
            status_code=409,
            detail=f"proposal already {proposal.status}",
        )

    publication = session.get(
        PublicationRecord,
        proposal.publication_id,
    )
    proposal.status = decision
    proposal.reviewer = reviewer
    proposal.reason = reason
    proposal.decided_at = utcnow()

    add_audit(
        session,
        job_id=publication.job_id if publication else None,
        event_type=f"optimizer_proposal_{decision}",
        actor=reviewer,
        payload={
            "proposal_id": proposal.id,
            "reason": reason,
        },
    )
    session.commit()
    session.refresh(proposal)
    return _response(proposal)
