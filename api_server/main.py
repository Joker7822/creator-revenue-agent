from datetime import datetime

from fastapi import Depends, FastAPI

from api_server.auth import require_service_token
from api_server.db import SessionLocal, init_db
from api_server.experiments import (
    assign_subject,
    cancel_experiment,
    complete_experiment,
    create_experiment,
    get_experiment,
    get_experiment_results,
    link_experiment_transaction,
    record_experiment_event,
    start_experiment,
)
from api_server.optimizer import (
    create_optimization_proposal,
    decide_optimization_proposal,
    get_optimization_proposal,
)
from api_server.repository import (
    create_approval,
    create_job,
    create_product,
    decide_approval,
    get_approval,
    get_audit_events,
    get_metrics,
    get_product,
    get_publication,
    get_revenue,
    publish_job,
    record_analytics_event,
    record_transaction,
    set_policy_result,
)
from api_server.schemas import (
    AnalyticsEventCreateRequest,
    AnalyticsEventResponse,
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalResponse,
    AuditEventResponse,
    ContentGenerateRequest,
    ContentGenerateResponse,
    ExperimentActorRequest,
    ExperimentAssignmentCreateRequest,
    ExperimentAssignmentResponse,
    ExperimentCancelRequest,
    ExperimentCompleteRequest,
    ExperimentCreateRequest,
    ExperimentEventCreateRequest,
    ExperimentEventResponse,
    ExperimentResponse,
    ExperimentResultsResponse,
    ExperimentTransactionLinkRequest,
    ExperimentTransactionLinkResponse,
    MetricsResponse,
    OptimizationDecisionRequest,
    OptimizationProposalCreateRequest,
    OptimizationProposalResponse,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    ProductCreateRequest,
    ProductResponse,
    PublicationResponse,
    PublishRequest,
    RevenueResponse,
    TransactionCreateRequest,
    TransactionResponse,
)
from api_server.services import evaluate_policy, generate_campaign_metadata


init_db()

app = FastAPI(
    title="creator-revenue-agent internal API",
    version="0.9.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/content/generate",
    response_model=ContentGenerateResponse,
    dependencies=[Depends(require_service_token)],
)
def content_generate(
    request: ContentGenerateRequest,
) -> ContentGenerateResponse:
    response = generate_campaign_metadata(request)
    with SessionLocal() as session:
        create_job(session, request, response)
    return response


@app.post(
    "/v1/policy/evaluate",
    response_model=PolicyEvaluateResponse,
    dependencies=[Depends(require_service_token)],
)
def policy_evaluate(
    request: PolicyEvaluateRequest,
) -> PolicyEvaluateResponse:
    response = evaluate_policy(request)
    if request.job_id:
        with SessionLocal() as session:
            set_policy_result(
                session,
                job_id=request.job_id,
                allowed=response.allowed,
                reasons=response.reasons,
            )
    return response


@app.post(
    "/v1/approvals",
    response_model=ApprovalResponse,
    dependencies=[Depends(require_service_token)],
)
def approval_create(
    request: ApprovalCreateRequest,
) -> ApprovalResponse:
    with SessionLocal() as session:
        return create_approval(
            session,
            job_id=request.job_id,
            required=request.required,
        )


@app.get(
    "/v1/approvals/{job_id}",
    response_model=ApprovalResponse,
    dependencies=[Depends(require_service_token)],
)
def approval_get(job_id: str) -> ApprovalResponse:
    with SessionLocal() as session:
        return get_approval(session, job_id)


@app.post(
    "/v1/approvals/{job_id}/approve",
    response_model=ApprovalResponse,
    dependencies=[Depends(require_service_token)],
)
def approval_approve(
    job_id: str,
    request: ApprovalDecisionRequest,
) -> ApprovalResponse:
    with SessionLocal() as session:
        return decide_approval(
            session,
            job_id=job_id,
            decision="approved",
            reviewer=request.reviewer,
            reason=request.reason,
        )


@app.post(
    "/v1/approvals/{job_id}/reject",
    response_model=ApprovalResponse,
    dependencies=[Depends(require_service_token)],
)
def approval_reject(
    job_id: str,
    request: ApprovalDecisionRequest,
) -> ApprovalResponse:
    with SessionLocal() as session:
        return decide_approval(
            session,
            job_id=job_id,
            decision="rejected",
            reviewer=request.reviewer,
            reason=request.reason,
        )


@app.post(
    "/v1/publish",
    response_model=PublicationResponse,
    dependencies=[Depends(require_service_token)],
)
def publish(request: PublishRequest) -> PublicationResponse:
    with SessionLocal() as session:
        return publish_job(
            session,
            job_id=request.job_id,
            destination=request.destination,
            publisher=request.publisher,
        )


@app.get(
    "/v1/publications/{job_id}",
    response_model=PublicationResponse,
    dependencies=[Depends(require_service_token)],
)
def publication_get(job_id: str) -> PublicationResponse:
    with SessionLocal() as session:
        return get_publication(session, job_id)


@app.post(
    "/v1/products",
    response_model=ProductResponse,
    dependencies=[Depends(require_service_token)],
)
def product_create(request: ProductCreateRequest) -> ProductResponse:
    with SessionLocal() as session:
        return create_product(
            session,
            publication_id=request.publication_id,
            name=request.name,
            currency=request.currency,
            price_minor_units=request.price_minor_units,
        )


@app.get(
    "/v1/products/{product_id}",
    response_model=ProductResponse,
    dependencies=[Depends(require_service_token)],
)
def product_get(product_id: str) -> ProductResponse:
    with SessionLocal() as session:
        return get_product(session, product_id)


@app.post(
    "/v1/transactions",
    response_model=TransactionResponse,
    dependencies=[Depends(require_service_token)],
)
def transaction_create(
    request: TransactionCreateRequest,
) -> TransactionResponse:
    with SessionLocal() as session:
        return record_transaction(
            session,
            transaction_id=request.transaction_id,
            product_id=request.product_id,
            kind=request.kind,
            amount_minor_units=request.amount_minor_units,
            currency=request.currency,
            occurred_at=request.occurred_at,
        )


@app.get(
    "/v1/revenue",
    response_model=RevenueResponse,
    dependencies=[Depends(require_service_token)],
)
def revenue_get(since: datetime | None = None) -> RevenueResponse:
    with SessionLocal() as session:
        return get_revenue(session, since=since)


@app.post(
    "/v1/events",
    response_model=AnalyticsEventResponse,
    dependencies=[Depends(require_service_token)],
)
def event_create(
    request: AnalyticsEventCreateRequest,
) -> AnalyticsEventResponse:
    with SessionLocal() as session:
        return record_analytics_event(
            session,
            event_id=request.event_id,
            publication_id=request.publication_id,
            event_type=request.event_type,
            occurred_at=request.occurred_at,
            metadata=request.metadata,
        )


@app.get(
    "/v1/metrics",
    response_model=MetricsResponse,
    dependencies=[Depends(require_service_token)],
)
def metrics_get(
    window: str = "7d",
    publication_id: str | None = None,
) -> MetricsResponse:
    with SessionLocal() as session:
        return get_metrics(
            session,
            window=window,
            publication_id=publication_id,
        )


@app.post(
    "/v1/optimizer/proposals",
    response_model=OptimizationProposalResponse,
    dependencies=[Depends(require_service_token)],
)
def optimizer_proposal_create(
    request: OptimizationProposalCreateRequest,
) -> OptimizationProposalResponse:
    with SessionLocal() as session:
        return create_optimization_proposal(
            session,
            publication_id=request.publication_id,
            window=request.window,
        )


@app.get(
    "/v1/optimizer/proposals/{proposal_id}",
    response_model=OptimizationProposalResponse,
    dependencies=[Depends(require_service_token)],
)
def optimizer_proposal_get(
    proposal_id: str,
) -> OptimizationProposalResponse:
    with SessionLocal() as session:
        return get_optimization_proposal(session, proposal_id)


@app.post(
    "/v1/optimizer/proposals/{proposal_id}/approve",
    response_model=OptimizationProposalResponse,
    dependencies=[Depends(require_service_token)],
)
def optimizer_proposal_approve(
    proposal_id: str,
    request: OptimizationDecisionRequest,
) -> OptimizationProposalResponse:
    with SessionLocal() as session:
        return decide_optimization_proposal(
            session,
            proposal_id=proposal_id,
            decision="approved",
            reviewer=request.reviewer,
            reason=request.reason,
        )


@app.post(
    "/v1/optimizer/proposals/{proposal_id}/reject",
    response_model=OptimizationProposalResponse,
    dependencies=[Depends(require_service_token)],
)
def optimizer_proposal_reject(
    proposal_id: str,
    request: OptimizationDecisionRequest,
) -> OptimizationProposalResponse:
    with SessionLocal() as session:
        return decide_optimization_proposal(
            session,
            proposal_id=proposal_id,
            decision="rejected",
            reviewer=request.reviewer,
            reason=request.reason,
        )


@app.post(
    "/v1/experiments",
    response_model=ExperimentResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_create(
    request: ExperimentCreateRequest,
) -> ExperimentResponse:
    with SessionLocal() as session:
        return create_experiment(
            session,
            proposal_id=request.proposal_id,
            recommendation_index=request.recommendation_index,
            owner=request.owner,
        )


@app.get(
    "/v1/experiments/{experiment_id}",
    response_model=ExperimentResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_get(
    experiment_id: str,
) -> ExperimentResponse:
    with SessionLocal() as session:
        return get_experiment(session, experiment_id)


@app.post(
    "/v1/experiments/{experiment_id}/start",
    response_model=ExperimentResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_start(
    experiment_id: str,
    request: ExperimentActorRequest,
) -> ExperimentResponse:
    with SessionLocal() as session:
        return start_experiment(
            session,
            experiment_id=experiment_id,
            actor=request.actor,
        )


@app.post(
    "/v1/experiments/{experiment_id}/complete",
    response_model=ExperimentResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_complete(
    experiment_id: str,
    request: ExperimentCompleteRequest,
) -> ExperimentResponse:
    with SessionLocal() as session:
        return complete_experiment(
            session,
            experiment_id=experiment_id,
            actor=request.actor,
            outcome=request.outcome,
        )


@app.post(
    "/v1/experiments/{experiment_id}/cancel",
    response_model=ExperimentResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_cancel(
    experiment_id: str,
    request: ExperimentCancelRequest,
) -> ExperimentResponse:
    with SessionLocal() as session:
        return cancel_experiment(
            session,
            experiment_id=experiment_id,
            actor=request.actor,
            reason=request.reason,
        )


@app.post(
    "/v1/experiments/{experiment_id}/assignments",
    response_model=ExperimentAssignmentResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_assignment_create(
    experiment_id: str,
    request: ExperimentAssignmentCreateRequest,
) -> ExperimentAssignmentResponse:
    with SessionLocal() as session:
        return assign_subject(
            session,
            experiment_id=experiment_id,
            subject_key=request.subject_key,
        )


@app.post(
    "/v1/experiments/{experiment_id}/events",
    response_model=ExperimentEventResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_event_create(
    experiment_id: str,
    request: ExperimentEventCreateRequest,
) -> ExperimentEventResponse:
    with SessionLocal() as session:
        return record_experiment_event(
            session,
            experiment_id=experiment_id,
            event_id=request.event_id,
            assignment_id=request.assignment_id,
            event_type=request.event_type,
            occurred_at=request.occurred_at,
        )


@app.post(
    "/v1/experiments/{experiment_id}/transactions",
    response_model=ExperimentTransactionLinkResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_transaction_link(
    experiment_id: str,
    request: ExperimentTransactionLinkRequest,
) -> ExperimentTransactionLinkResponse:
    with SessionLocal() as session:
        return link_experiment_transaction(
            session,
            experiment_id=experiment_id,
            transaction_id=request.transaction_id,
            assignment_id=request.assignment_id,
        )


@app.get(
    "/v1/experiments/{experiment_id}/results",
    response_model=ExperimentResultsResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_results_get(
    experiment_id: str,
) -> ExperimentResultsResponse:
    with SessionLocal() as session:
        return get_experiment_results(
            session,
            experiment_id=experiment_id,
        )


@app.get(
    "/v1/audit/{job_id}",
    response_model=list[AuditEventResponse],
    dependencies=[Depends(require_service_token)],
)
def audit_get(job_id: str) -> list[AuditEventResponse]:
    with SessionLocal() as session:
        return get_audit_events(session, job_id)
