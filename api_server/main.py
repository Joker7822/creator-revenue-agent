from contextlib import asynccontextmanager
from datetime import datetime
from time import perf_counter

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, PlainTextResponse

from api_server.abuse_protection import (
    RequestBodyLimitMiddleware,
    require_billing_rate_limit,
    require_credential_rate_limit,
    require_rollout_rate_limit,
    require_verification_webhook_rate_limit,
)
from api_server.audit_anchor import (
    audit_anchor_freshness,
    create_audit_anchor,
    verify_external_audit_anchor,
)
from api_server.audit_integrity import verify_audit_chain
from api_server.auth import (
    ServicePrincipal,
    get_credential_status,
    get_signing_key_status,
    issue_service_credential,
    require_roles,
    require_service_token,
    revoke_service_credential,
)
from api_server.db import SessionLocal
from api_server.migration_runtime import assert_database_current
from api_server.experiment_statistics import (
    create_experiment_review,
    evaluate_experiment_statistics,
    get_experiment_review,
)
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
from api_server.observability import (
    bind_request_context,
    log_request_completed,
    log_unhandled_exception,
    operational_metrics,
    operational_status_snapshot,
    prometheus_metrics,
    request_route_template,
    reset_request_context,
    resolve_request_context,
)
from api_server.optimizer import (
    create_optimization_proposal,
    decide_optimization_proposal,
    get_optimization_proposal,
)
from api_server.rollouts import (
    apply_change_set,
    create_change_set,
    decide_change_set,
    get_change_set,
    get_rollback,
    get_rollout,
    monitor_rollout,
    rollback_rollout,
)
from api_server.readiness import production_readiness
from api_server.repository import (
    create_approval,
    create_job,
    create_product,
    decide_approval,
    get_approval,
    get_audit_events,
    get_job_policy_request,
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
    AuditAnchorFreshnessResponse,
    AuditAnchorReceiptResponse,
    AuditAnchorVerificationResponse,
    AuditEventResponse,
    AuditIntegrityResponse,
    ContentGenerateRequest,
    ContentGenerateResponse,
    CredentialIssueRequest,
    CredentialResponse,
    CredentialRevokeRequest,
    CredentialStatusResponse,
    ChangeSetCreateRequest,
    ChangeSetDecisionRequest,
    ChangeSetResponse,
    ExperimentActorRequest,
    ExperimentAssignmentCreateRequest,
    ExperimentAssignmentResponse,
    ExperimentCancelRequest,
    ExperimentCompleteRequest,
    ExperimentCreateRequest,
    ExperimentEventCreateRequest,
    ExperimentEventResponse,
    ExperimentResponse,
    ExperimentResultReviewCreateRequest,
    ExperimentResultReviewResponse,
    ExperimentStatisticsResponse,
    ExperimentResultsResponse,
    ExperimentTransactionLinkRequest,
    ExperimentTransactionLinkResponse,
    MetricsResponse,
    OperationalStatusResponse,
    OptimizationDecisionRequest,
    OptimizationProposalCreateRequest,
    OptimizationProposalResponse,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    ProductCreateRequest,
    ProductResponse,
    ProductionReadinessResponse,
    PublicationResponse,
    PublishRequest,
    RevenueResponse,
    RollbackRequest,
    RollbackResponse,
    RolloutApplyRequest,
    RolloutMonitorResponse,
    RolloutResponse,
    SigningKeyStatusResponse,
    TransactionCreateRequest,
    TransactionResponse,
    VerificationCreateRequest,
    VerificationResponse,
    VerificationRevokeRequest,
    VerificationWebhookKeyStatusResponse,
    VerificationWebhookResponse,
)
from api_server.services import evaluate_policy, generate_campaign_metadata
from api_server.verification import (
    create_verification,
    get_verification,
    resolve_content_request,
    revoke_verification,
)
from api_server.verification_webhooks import (
    get_webhook_key_status,
    process_verification_webhook,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    assert_database_current()
    yield


app = FastAPI(
    title="creator-revenue-agent internal API",
    version="0.26.0",
    lifespan=lifespan,
)

# Added before the function middleware so observability wraps
# body-limit responses and records their 413 status.
app.add_middleware(RequestBodyLimitMiddleware)


@app.middleware("http")
async def observability_middleware(
    request: Request,
    call_next,
):
    context = resolve_request_context(
        request_id_header=request.headers.get("X-Request-ID"),
        traceparent_header=request.headers.get("traceparent"),
    )
    tokens = bind_request_context(context)
    started = perf_counter()

    try:
        response = await call_next(request)
    except HTTPException as exc:
        duration_ms = (perf_counter() - started) * 1000
        route = request_route_template(request.scope)
        operational_metrics.record(
            method=request.method,
            route=route,
            status_code=exc.status_code,
            duration_ms=duration_ms,
        )
        log_request_completed(
            method=request.method,
            route=route,
            status_code=exc.status_code,
            duration_ms=duration_ms,
        )
        headers = dict(exc.headers or {})
        headers["X-Request-ID"] = context.request_id
        headers["X-Trace-ID"] = context.trace_id
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "request_id": context.request_id,
                "trace_id": context.trace_id,
            },
            headers=headers,
        )
    except Exception as exc:
        duration_ms = (perf_counter() - started) * 1000
        route = request_route_template(request.scope)
        operational_metrics.record(
            method=request.method,
            route=route,
            status_code=500,
            duration_ms=duration_ms,
        )
        log_unhandled_exception(
            method=request.method,
            route=route,
            duration_ms=duration_ms,
            exception_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "internal server error",
                "error_code": "internal_server_error",
                "request_id": context.request_id,
                "trace_id": context.trace_id,
            },
            headers={
                "X-Request-ID": context.request_id,
                "X-Trace-ID": context.trace_id,
            },
        )
    else:
        duration_ms = (perf_counter() - started) * 1000
        route = request_route_template(request.scope)
        operational_metrics.record(
            method=request.method,
            route=route,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        log_request_completed(
            method=request.method,
            route=route,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = context.request_id
        response.headers["X-Trace-ID"] = context.trace_id
        return response
    finally:
        reset_request_context(tokens)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/v1/ops/metrics",
    response_class=PlainTextResponse,
)
def operational_metrics_export(
    principal: ServicePrincipal = Depends(
        require_roles("metrics_reader")
    ),
) -> PlainTextResponse:
    del principal
    return PlainTextResponse(
        prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get(
    "/v1/ops/status",
    response_model=OperationalStatusResponse,
    dependencies=[Depends(require_service_token)],
)
def operational_status() -> OperationalStatusResponse:
    return OperationalStatusResponse.model_validate(
        operational_status_snapshot()
    )


@app.get(
    "/ready",
    response_model=ProductionReadinessResponse,
)
def ready(
    response: Response,
) -> ProductionReadinessResponse:
    with SessionLocal() as session:
        result = production_readiness(session)
    if not result.ready:
        response.status_code = 503
    return result


@app.post(
    "/v1/auth/credentials",
    response_model=CredentialResponse,
)
def credential_issue(
    request: CredentialIssueRequest,
    principal: ServicePrincipal = Depends(
        require_roles("credential_admin")
    ),
    _rate_limit: None = Depends(
        require_credential_rate_limit
    ),
) -> CredentialResponse:
    with SessionLocal() as session:
        return issue_service_credential(
            session,
            issuer_principal=principal,
            subject=request.subject,
            roles=request.roles,
            ttl_seconds=request.ttl_seconds,
        )


@app.get(
    "/v1/auth/credentials/{credential_id}",
    response_model=CredentialStatusResponse,
)
def credential_status(
    credential_id: str,
    principal: ServicePrincipal = Depends(
        require_roles("credential_admin")
    ),
) -> CredentialStatusResponse:
    del principal
    with SessionLocal() as session:
        return get_credential_status(
            session,
            credential_id=credential_id,
        )


@app.post(
    "/v1/auth/credentials/{credential_id}/revoke",
    response_model=CredentialStatusResponse,
)
def credential_revoke(
    credential_id: str,
    request: CredentialRevokeRequest,
    principal: ServicePrincipal = Depends(
        require_roles("credential_admin")
    ),
    _rate_limit: None = Depends(
        require_credential_rate_limit
    ),
) -> CredentialStatusResponse:
    with SessionLocal() as session:
        return revoke_service_credential(
            session,
            credential_id=credential_id,
            revoked_by=principal.subject,
            reason=request.reason,
        )


@app.get(
    "/v1/auth/signing-keys",
    response_model=SigningKeyStatusResponse,
)
def signing_key_status(
    principal: ServicePrincipal = Depends(
        require_roles("credential_admin")
    ),
) -> SigningKeyStatusResponse:
    del principal
    return get_signing_key_status()


@app.get(
    "/v1/auth/verification-webhook-keys",
    response_model=VerificationWebhookKeyStatusResponse,
)
def verification_webhook_key_status(
    principal: ServicePrincipal = Depends(
        require_roles("credential_admin")
    ),
) -> VerificationWebhookKeyStatusResponse:
    del principal
    return get_webhook_key_status()


@app.post(
    "/v1/webhooks/verifications",
    response_model=VerificationWebhookResponse,
)
async def verification_provider_webhook(
    request: Request,
    _rate_limit: None = Depends(
        require_verification_webhook_rate_limit
    ),
    provider: str = Header(
        ...,
        alias="X-Verification-Provider",
    ),
    key_id: str | None = Header(
        default=None,
        alias="X-Verification-Key-Id",
    ),
    event_id: str = Header(
        ...,
        alias="X-Verification-Event-Id",
    ),
    timestamp_value: str = Header(
        ...,
        alias="X-Verification-Timestamp",
    ),
    signature: str = Header(
        ...,
        alias="X-Verification-Signature",
    ),
) -> VerificationWebhookResponse:
    body = await request.body()
    with SessionLocal() as session:
        return process_verification_webhook(
            session,
            provider=provider,
            key_id=key_id,
            event_id=event_id,
            timestamp_value=timestamp_value,
            signature=signature,
            body=body,
        )


@app.post(
    "/v1/verifications",
    response_model=VerificationResponse,
)
def verification_create(
    request: VerificationCreateRequest,
    principal: ServicePrincipal = Depends(
        require_roles("verification_writer")
    ),
) -> VerificationResponse:
    with SessionLocal() as session:
        return create_verification(
            session,
            subject_ref=request.subject_ref,
            kind=request.kind,
            source=request.source,
            source_record_ref=request.source_record_ref,
            age_years=request.age_years,
            expires_at=request.expires_at,
            created_by=principal.subject,
        )


@app.get(
    "/v1/verifications/{verification_id}",
    response_model=VerificationResponse,
    dependencies=[Depends(require_service_token)],
)
def verification_get(
    verification_id: str,
) -> VerificationResponse:
    with SessionLocal() as session:
        return get_verification(session, verification_id)


@app.post(
    "/v1/verifications/{verification_id}/revoke",
    response_model=VerificationResponse,
)
def verification_revoke(
    verification_id: str,
    request: VerificationRevokeRequest,
    principal: ServicePrincipal = Depends(
        require_roles("verification_writer")
    ),
) -> VerificationResponse:
    with SessionLocal() as session:
        return revoke_verification(
            session,
            verification_id=verification_id,
            actor=principal.subject,
            reason=request.reason,
        )


@app.post(
    "/v1/content/generate",
    response_model=ContentGenerateResponse,
    dependencies=[Depends(require_service_token)],
)
def content_generate(
    request: ContentGenerateRequest,
) -> ContentGenerateResponse:
    with SessionLocal() as session:
        trusted_request = resolve_content_request(
            session,
            request,
        )
        response = generate_campaign_metadata(
            trusted_request
        )
        create_job(
            session,
            trusted_request,
            response,
        )
        return response


@app.post(
    "/v1/policy/evaluate",
    response_model=PolicyEvaluateResponse,
    dependencies=[Depends(require_service_token)],
)
def policy_evaluate(
    request: PolicyEvaluateRequest,
) -> PolicyEvaluateResponse:
    if request.job_id:
        with SessionLocal() as session:
            trusted_request = get_job_policy_request(
                session,
                job_id=request.job_id,
                asset_ref=request.asset_ref,
            )
            response = evaluate_policy(trusted_request)
            set_policy_result(
                session,
                job_id=request.job_id,
                allowed=response.allowed,
                reasons=response.reasons,
            )
            return response

    return evaluate_policy(request)


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
)
def approval_approve(
    job_id: str,
    request: ApprovalDecisionRequest,
    principal: ServicePrincipal = Depends(
        require_roles("reviewer")
    ),
) -> ApprovalResponse:
    with SessionLocal() as session:
        return decide_approval(
            session,
            job_id=job_id,
            decision="approved",
            reviewer=principal.subject,
            reason=request.reason,
        )


@app.post(
    "/v1/approvals/{job_id}/reject",
    response_model=ApprovalResponse,
)
def approval_reject(
    job_id: str,
    request: ApprovalDecisionRequest,
    principal: ServicePrincipal = Depends(
        require_roles("reviewer")
    ),
) -> ApprovalResponse:
    with SessionLocal() as session:
        return decide_approval(
            session,
            job_id=job_id,
            decision="rejected",
            reviewer=principal.subject,
            reason=request.reason,
        )


@app.post(
    "/v1/publish",
    response_model=PublicationResponse,
)
def publish(
    request: PublishRequest,
    principal: ServicePrincipal = Depends(
        require_roles("publisher")
    ),
) -> PublicationResponse:
    with SessionLocal() as session:
        return publish_job(
            session,
            job_id=request.job_id,
            destination=request.destination,
            publisher=principal.subject,
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
    dependencies=[
        Depends(require_roles("billing_writer")),
        Depends(require_billing_rate_limit),
    ],
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
    dependencies=[
        Depends(require_roles("billing_writer")),
        Depends(require_billing_rate_limit),
    ],
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
            original_sale_id=request.original_sale_id,
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
)
def optimizer_proposal_approve(
    proposal_id: str,
    request: OptimizationDecisionRequest,
    principal: ServicePrincipal = Depends(
        require_roles("reviewer")
    ),
) -> OptimizationProposalResponse:
    with SessionLocal() as session:
        return decide_optimization_proposal(
            session,
            proposal_id=proposal_id,
            decision="approved",
            reviewer=principal.subject,
            reason=request.reason,
        )


@app.post(
    "/v1/optimizer/proposals/{proposal_id}/reject",
    response_model=OptimizationProposalResponse,
)
def optimizer_proposal_reject(
    proposal_id: str,
    request: OptimizationDecisionRequest,
    principal: ServicePrincipal = Depends(
        require_roles("reviewer")
    ),
) -> OptimizationProposalResponse:
    with SessionLocal() as session:
        return decide_optimization_proposal(
            session,
            proposal_id=proposal_id,
            decision="rejected",
            reviewer=principal.subject,
            reason=request.reason,
        )


@app.post(
    "/v1/experiments",
    response_model=ExperimentResponse,
)
def experiment_create(
    request: ExperimentCreateRequest,
    principal: ServicePrincipal = Depends(
        require_roles("experiment_operator")
    ),
) -> ExperimentResponse:
    with SessionLocal() as session:
        return create_experiment(
            session,
            proposal_id=request.proposal_id,
            recommendation_index=request.recommendation_index,
            owner=principal.subject,
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
)
def experiment_start(
    experiment_id: str,
    request: ExperimentActorRequest,
    principal: ServicePrincipal = Depends(
        require_roles("experiment_operator")
    ),
) -> ExperimentResponse:
    with SessionLocal() as session:
        return start_experiment(
            session,
            experiment_id=experiment_id,
            actor=principal.subject,
        )


@app.post(
    "/v1/experiments/{experiment_id}/complete",
    response_model=ExperimentResponse,
)
def experiment_complete(
    experiment_id: str,
    request: ExperimentCompleteRequest,
    principal: ServicePrincipal = Depends(
        require_roles("experiment_operator")
    ),
) -> ExperimentResponse:
    with SessionLocal() as session:
        return complete_experiment(
            session,
            experiment_id=experiment_id,
            actor=principal.subject,
            outcome=request.outcome,
        )


@app.post(
    "/v1/experiments/{experiment_id}/cancel",
    response_model=ExperimentResponse,
)
def experiment_cancel(
    experiment_id: str,
    request: ExperimentCancelRequest,
    principal: ServicePrincipal = Depends(
        require_roles("experiment_operator")
    ),
) -> ExperimentResponse:
    with SessionLocal() as session:
        return cancel_experiment(
            session,
            experiment_id=experiment_id,
            actor=principal.subject,
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
    "/v1/experiments/{experiment_id}/statistics",
    response_model=ExperimentStatisticsResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_statistics_get(
    experiment_id: str,
) -> ExperimentStatisticsResponse:
    with SessionLocal() as session:
        return evaluate_experiment_statistics(
            session,
            experiment_id=experiment_id,
        )


@app.post(
    "/v1/experiments/{experiment_id}/reviews",
    response_model=ExperimentResultReviewResponse,
)
def experiment_review_create(
    experiment_id: str,
    request: ExperimentResultReviewCreateRequest,
    principal: ServicePrincipal = Depends(
        require_roles("reviewer")
    ),
) -> ExperimentResultReviewResponse:
    with SessionLocal() as session:
        return create_experiment_review(
            session,
            experiment_id=experiment_id,
            decision=request.decision,
            reviewer=principal.subject,
            reason=request.reason,
        )


@app.get(
    "/v1/experiments/{experiment_id}/review",
    response_model=ExperimentResultReviewResponse,
    dependencies=[Depends(require_service_token)],
)
def experiment_review_get(
    experiment_id: str,
) -> ExperimentResultReviewResponse:
    with SessionLocal() as session:
        return get_experiment_review(
            session,
            experiment_id=experiment_id,
        )


@app.post(
    "/v1/change-sets",
    response_model=ChangeSetResponse,
)
def change_set_create(
    request: ChangeSetCreateRequest,
    principal: ServicePrincipal = Depends(
        require_roles("planner")
    ),
) -> ChangeSetResponse:
    with SessionLocal() as session:
        return create_change_set(
            session,
            review_id=request.review_id,
            created_by=principal.subject,
        )


@app.get(
    "/v1/change-sets/{change_set_id}",
    response_model=ChangeSetResponse,
    dependencies=[Depends(require_service_token)],
)
def change_set_get(
    change_set_id: str,
) -> ChangeSetResponse:
    with SessionLocal() as session:
        return get_change_set(session, change_set_id)


@app.post(
    "/v1/change-sets/{change_set_id}/approve",
    response_model=ChangeSetResponse,
)
def change_set_approve(
    change_set_id: str,
    request: ChangeSetDecisionRequest,
    principal: ServicePrincipal = Depends(
        require_roles("release_manager")
    ),
) -> ChangeSetResponse:
    with SessionLocal() as session:
        return decide_change_set(
            session,
            change_set_id=change_set_id,
            decision="approved",
            actor=principal.subject,
            reason=request.reason,
        )


@app.post(
    "/v1/change-sets/{change_set_id}/reject",
    response_model=ChangeSetResponse,
)
def change_set_reject(
    change_set_id: str,
    request: ChangeSetDecisionRequest,
    principal: ServicePrincipal = Depends(
        require_roles("release_manager")
    ),
) -> ChangeSetResponse:
    with SessionLocal() as session:
        return decide_change_set(
            session,
            change_set_id=change_set_id,
            decision="rejected",
            actor=principal.subject,
            reason=request.reason,
        )


@app.post(
    "/v1/change-sets/{change_set_id}/apply",
    response_model=RolloutResponse,
)
def change_set_apply(
    change_set_id: str,
    request: RolloutApplyRequest,
    principal: ServicePrincipal = Depends(
        require_roles("rollout_operator")
    ),
    _rate_limit: None = Depends(
        require_rollout_rate_limit
    ),
) -> RolloutResponse:
    with SessionLocal() as session:
        return apply_change_set(
            session,
            change_set_id=change_set_id,
            actor=principal.subject,
        )


@app.get(
    "/v1/rollouts/{rollout_id}",
    response_model=RolloutResponse,
    dependencies=[Depends(require_service_token)],
)
def rollout_get(
    rollout_id: str,
) -> RolloutResponse:
    with SessionLocal() as session:
        return get_rollout(session, rollout_id)


@app.get(
    "/v1/rollouts/{rollout_id}/monitor",
    response_model=RolloutMonitorResponse,
    dependencies=[Depends(require_service_token)],
)
def rollout_monitor(
    rollout_id: str,
) -> RolloutMonitorResponse:
    with SessionLocal() as session:
        return monitor_rollout(
            session,
            rollout_id=rollout_id,
        )


@app.post(
    "/v1/rollouts/{rollout_id}/rollback",
    response_model=RollbackResponse,
)
def rollout_rollback(
    rollout_id: str,
    request: RollbackRequest,
    principal: ServicePrincipal = Depends(
        require_roles("incident_manager")
    ),
    _rate_limit: None = Depends(
        require_rollout_rate_limit
    ),
) -> RollbackResponse:
    with SessionLocal() as session:
        return rollback_rollout(
            session,
            rollout_id=rollout_id,
            actor=principal.subject,
            reason=request.reason,
        )


@app.get(
    "/v1/rollbacks/{rollback_id}",
    response_model=RollbackResponse,
    dependencies=[Depends(require_service_token)],
)
def rollback_get(
    rollback_id: str,
) -> RollbackResponse:
    with SessionLocal() as session:
        return get_rollback(
            session,
            rollback_id=rollback_id,
        )


@app.post(
    "/v1/audit/anchors",
    response_model=AuditAnchorReceiptResponse,
)
def audit_anchor_create(
    principal: ServicePrincipal = Depends(
        require_roles("audit_anchor_operator")
    ),
) -> AuditAnchorReceiptResponse:
    with SessionLocal() as session:
        return create_audit_anchor(
            session,
            actor=principal.subject,
        )


@app.get(
    "/v1/audit/anchors/verify",
    response_model=AuditAnchorVerificationResponse,
    dependencies=[Depends(require_service_token)],
)
def audit_anchor_verify() -> AuditAnchorVerificationResponse:
    with SessionLocal() as session:
        return verify_external_audit_anchor(session)


@app.get(
    "/v1/audit/anchors/freshness",
    response_model=AuditAnchorFreshnessResponse,
    dependencies=[Depends(require_service_token)],
)
def audit_anchor_freshness_get() -> AuditAnchorFreshnessResponse:
    with SessionLocal() as session:
        return audit_anchor_freshness(session)


@app.get(
    "/v1/audit/integrity",
    response_model=AuditIntegrityResponse,
    dependencies=[Depends(require_service_token)],
)
def audit_integrity_get() -> AuditIntegrityResponse:
    with SessionLocal() as session:
        return verify_audit_chain(session)


@app.get(
    "/v1/audit/{job_id}",
    response_model=list[AuditEventResponse],
    dependencies=[Depends(require_service_token)],
)
def audit_get(job_id: str) -> list[AuditEventResponse]:
    with SessionLocal() as session:
        return get_audit_events(session, job_id)
