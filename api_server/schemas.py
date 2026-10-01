from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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


class ApprovalCreateRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=128)
    required: bool = True


class ApprovalDecisionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=1000)


class ApprovalResponse(BaseModel):
    job_id: str
    status: str
    required: bool
    reviewer: str | None
    reason: str | None
    created_at: datetime
    decided_at: datetime | None


class PublishRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=128)
    destination: str = Field(default="internal", min_length=1, max_length=120)
    publisher: str = Field(default="agent", min_length=1, max_length=120)


class PublicationResponse(BaseModel):
    publication_id: str
    job_id: str
    status: str
    destination: str
    publisher: str
    published_at: datetime


class ProductCreateRequest(BaseModel):
    publication_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    currency: str = Field(min_length=3, max_length=3)
    price_minor_units: int = Field(ge=0, le=1_000_000_000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("currency must be a 3-letter code")
        return value


class ProductResponse(BaseModel):
    product_id: str
    publication_id: str
    name: str
    currency: str
    price_minor_units: int
    active: bool
    created_at: datetime


class TransactionCreateRequest(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=128)
    kind: Literal["sale", "refund"]
    amount_minor_units: int = Field(gt=0, le=1_000_000_000)
    currency: str = Field(min_length=3, max_length=3)
    occurred_at: datetime | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("currency must be a 3-letter code")
        return value


class TransactionResponse(BaseModel):
    transaction_id: str
    product_id: str
    kind: str
    amount_minor_units: int
    currency: str
    occurred_at: datetime
    recorded_at: datetime


class RevenueCurrencySummary(BaseModel):
    currency: str
    sales_count: int
    refund_count: int
    sales_minor_units: int
    refunds_minor_units: int
    net_revenue_minor_units: int


class RevenueResponse(BaseModel):
    since: datetime | None
    currencies: list[RevenueCurrencySummary]


class AnalyticsEventCreateRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    publication_id: str = Field(min_length=1, max_length=128)
    event_type: Literal["impression", "click"]
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalyticsEventResponse(BaseModel):
    event_id: str
    publication_id: str
    event_type: str
    occurred_at: datetime
    recorded_at: datetime


class MetricsCurrencySummary(BaseModel):
    currency: str
    sales_count: int
    refund_count: int
    sales_minor_units: int
    refunds_minor_units: int
    net_revenue_minor_units: int


class MetricsResponse(BaseModel):
    window: str
    since: datetime
    publication_id: str | None
    impressions: int
    clicks: int
    purchases: int
    refunds: int
    ctr: float
    cvr: float
    currencies: list[MetricsCurrencySummary]


class OptimizationProposalCreateRequest(BaseModel):
    publication_id: str = Field(min_length=1, max_length=128)
    window: str = Field(default="7d", min_length=2, max_length=16)


class OptimizationDecisionRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=1000)


class OptimizationProposalResponse(BaseModel):
    proposal_id: str
    publication_id: str
    product_id: str
    window: str
    status: str
    metrics: dict[str, Any]
    recommendations: list[dict[str, Any]]
    reviewer: str | None
    reason: str | None
    created_at: datetime
    decided_at: datetime | None


class AuditEventResponse(BaseModel):
    id: int
    job_id: str | None
    event_type: str
    actor: str | None
    payload: dict
    created_at: datetime
