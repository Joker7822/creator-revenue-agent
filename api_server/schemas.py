from pydantic import BaseModel, Field


class ContentGenerateRequest(BaseModel):
    campaign_type: str = Field(min_length=1, max_length=80)
    target_segment: str = Field(min_length=1, max_length=80)
    price_cents: int = Field(ge=0, le=100_000_000)

    creator_age: int | None = Field(default=None, ge=0, le=130)
    age_verified: bool = False
    consent_verified: bool = False
    depicts_real_person: bool = False
    real_person_consent_verified: bool = False


class ContentGenerateResponse(BaseModel):
    job_id: str
    title: str
    teaser: str
    price_cents: int

    creator_age: int | None
    age_verified: bool
    consent_verified: bool
    depicts_real_person: bool
    real_person_consent_verified: bool

    asset_ref: str | None = None


class PolicyEvaluateRequest(BaseModel):
    job_id: str | None = None
    creator_age: int | None = Field(default=None, ge=0, le=130)
    age_verified: bool = False
    consent_verified: bool = False
    depicts_real_person: bool = False
    real_person_consent_verified: bool = False
    asset_ref: str | None = None


class PolicyEvaluateResponse(BaseModel):
    allowed: bool
    reasons: list[str]
