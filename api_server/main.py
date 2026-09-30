from fastapi import Depends, FastAPI

from api_server.auth import require_service_token
from api_server.schemas import (
    ContentGenerateRequest,
    ContentGenerateResponse,
    PolicyEvaluateRequest,
    PolicyEvaluateResponse,
)
from api_server.services import (
    evaluate_policy,
    generate_campaign_metadata,
)


app = FastAPI(
    title="creator-revenue-agent internal API",
    version="0.2.0",
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
    return generate_campaign_metadata(request)


@app.post(
    "/v1/policy/evaluate",
    response_model=PolicyEvaluateResponse,
    dependencies=[Depends(require_service_token)],
)
def policy_evaluate(
    request: PolicyEvaluateRequest,
) -> PolicyEvaluateResponse:
    return evaluate_policy(request)
