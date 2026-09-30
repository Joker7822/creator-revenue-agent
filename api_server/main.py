from fastapi import Depends, FastAPI

from api_server.auth import require_service_token
from api_server.db import SessionLocal, init_db
from api_server.repository import (
    create_approval,
    create_job,
    decide_approval,
    get_approval,
    get_audit_events,
    get_publication,
    publish_job,
    set_policy_result,
)
from api_server.schemas import (
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalResponse,
    AuditEventResponse,
    ContentGenerateRequest,
    ContentGenerateResponse,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
    PublicationResponse,
    PublishRequest,
)
from api_server.services import (
    evaluate_policy,
    generate_campaign_metadata,
)


init_db()

app = FastAPI(
    title="creator-revenue-agent internal API",
    version="0.4.0",
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
        create_job(
            session,
            request,
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
def approval_get(
    job_id: str,
) -> ApprovalResponse:
    with SessionLocal() as session:
        return get_approval(
            session,
            job_id,
        )


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
def publish(
    request: PublishRequest,
) -> PublicationResponse:
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
def publication_get(
    job_id: str,
) -> PublicationResponse:
    with SessionLocal() as session:
        return get_publication(
            session,
            job_id,
        )


@app.get(
    "/v1/audit/{job_id}",
    response_model=list[AuditEventResponse],
    dependencies=[Depends(require_service_token)],
)
def audit_get(
    job_id: str,
) -> list[AuditEventResponse]:
    with SessionLocal() as session:
        return get_audit_events(
            session,
            job_id,
        )
