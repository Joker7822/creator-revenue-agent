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
    creator_ref: str | None = Field(default=None, min_length=1, max_length=128)
    age_verification_id: str | None = Field(default=None, min_length=1, max_length=128)
    consent_verification_id: str | None = Field(default=None, min_length=1, max_length=128)
    real_person_consent_verification_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


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
    creator_ref: str | None = None
    age_verification_id: str | None = None
    consent_verification_id: str | None = None
    real_person_consent_verification_id: str | None = None
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


class VerificationCreateRequest(BaseModel):
    subject_ref: str = Field(min_length=1, max_length=128)
    kind: Literal[
        "age",
        "creator_consent",
        "real_person_consent",
    ]
    source: str = Field(min_length=1, max_length=120)
    source_record_ref: str | None = Field(default=None, max_length=200)
    age_years: int | None = Field(default=None, ge=0, le=130)
    expires_at: datetime | None = None


class VerificationRevokeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class VerificationResponse(BaseModel):
    verification_id: str
    subject_ref: str
    kind: str
    status: str
    source: str
    source_record_ref: str | None
    age_years: int | None
    created_by: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    revoked_by: str | None
    revoke_reason: str | None


class VerificationWebhookPayload(BaseModel):
    event_type: Literal[
        "verification.verified",
        "verification.revoked",
    ]
    provider_record_ref: str = Field(
        min_length=1,
        max_length=200,
    )
    subject_ref: str = Field(min_length=1, max_length=128)
    kind: Literal[
        "age",
        "creator_consent",
        "real_person_consent",
    ]
    age_years: int | None = Field(default=None, ge=0, le=130)
    expires_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=2000)


class VerificationWebhookResponse(BaseModel):
    provider: str
    key_id: str
    event_id: str
    event_type: str
    duplicate: bool
    verification: VerificationResponse


class VerificationWebhookKeyStatusResponse(BaseModel):
    key_id_required: bool
    providers: dict[str, list[str]]


class ApprovalCreateRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=128)
    required: bool = True


class ApprovalDecisionRequest(BaseModel):
    reviewer: str | None = Field(default=None, max_length=120)
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
    publisher: str | None = Field(default=None, max_length=120)


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
    original_sale_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
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
    original_sale_id: str | None
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
    reviewer: str | None = Field(default=None, max_length=120)
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


class ExperimentCreateRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=128)
    recommendation_index: int = Field(ge=0)
    owner: str | None = Field(default=None, max_length=120)


class ExperimentActorRequest(BaseModel):
    actor: str | None = Field(default=None, max_length=120)


class ExperimentCompleteRequest(BaseModel):
    actor: str | None = Field(default=None, max_length=120)
    outcome: dict[str, Any] = Field(default_factory=dict)


class ExperimentCancelRequest(BaseModel):
    actor: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=1000)


class ExperimentResponse(BaseModel):
    experiment_id: str
    proposal_id: str
    publication_id: str
    product_id: str
    recommendation_index: int
    status: str
    plan: dict[str, Any]
    owner: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    outcome: dict[str, Any] | None


class ExperimentAssignmentCreateRequest(BaseModel):
    subject_key: str = Field(min_length=1, max_length=512)


class ExperimentAssignmentResponse(BaseModel):
    assignment_id: str
    experiment_id: str
    arm: Literal["control", "variant"]
    assigned_at: datetime


class ExperimentEventCreateRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    assignment_id: str = Field(min_length=1, max_length=128)
    event_type: Literal["impression", "click"]
    occurred_at: datetime | None = None


class ExperimentEventResponse(BaseModel):
    event_id: str
    experiment_id: str
    assignment_id: str
    arm: Literal["control", "variant"]
    event_type: Literal["impression", "click"]
    occurred_at: datetime
    recorded_at: datetime


class ExperimentTransactionLinkRequest(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=128)
    assignment_id: str = Field(min_length=1, max_length=128)


class ExperimentTransactionLinkResponse(BaseModel):
    transaction_id: str
    experiment_id: str
    assignment_id: str
    arm: Literal["control", "variant"]
    kind: Literal["sale", "refund"]
    amount_minor_units: int
    currency: str
    linked_at: datetime


class ExperimentCurrencyResult(BaseModel):
    currency: str
    sales_minor_units: int
    refunds_minor_units: int
    net_revenue_minor_units: int


class ExperimentArmResult(BaseModel):
    arm: Literal["control", "variant"]
    assignments: int
    impressions: int
    clicks: int
    purchases: int
    refunds: int
    ctr: float
    cvr: float
    currencies: list[ExperimentCurrencyResult]


class ExperimentResultsResponse(BaseModel):
    experiment_id: str
    status: str
    evaluation_status: Literal[
        "insufficient_data",
        "ready_for_manual_review",
    ]
    control: ExperimentArmResult
    variant: ExperimentArmResult
    comparison: dict[str, Any]


class ProportionStatistic(BaseModel):
    numerator: int
    denominator: int
    rate: float | None
    ci_lower: float | None
    ci_upper: float | None


class ExperimentReadinessGates(BaseModel):
    min_runtime_hours: int
    runtime_hours: float
    runtime_passed: bool
    min_assignments_per_arm: int
    assignments_passed: bool
    min_impressions_per_arm: int
    impressions_passed: bool
    min_clicks_per_arm: int
    clicks_passed: bool
    all_passed: bool


class ExperimentStatisticalArm(BaseModel):
    arm: Literal["control", "variant"]
    assignments: int
    impressions: int
    clicks: int
    purchases: int
    refunds: int
    ctr: ProportionStatistic
    cvr: ProportionStatistic
    currencies: list[ExperimentCurrencyResult]


class ExperimentStatisticsResponse(BaseModel):
    experiment_id: str
    status: str
    confidence_level: float
    alpha: float
    gates: ExperimentReadinessGates
    control: ExperimentStatisticalArm
    variant: ExperimentStatisticalArm
    tests: dict[str, float | None]
    decision: Literal["manual_review_required"]
    winner: None = None


class ExperimentResultReviewCreateRequest(BaseModel):
    decision: Literal[
        "control_preferred",
        "variant_preferred",
        "inconclusive",
    ]
    reviewer: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=2000)


class ExperimentResultReviewResponse(BaseModel):
    review_id: str
    experiment_id: str
    decision: str
    reviewer: str
    reason: str | None
    statistics_snapshot: dict[str, Any]
    created_at: datetime


class ChangeSetCreateRequest(BaseModel):
    review_id: str = Field(min_length=1, max_length=128)
    created_by: str | None = Field(default=None, max_length=120)


class ChangeSetDecisionRequest(BaseModel):
    actor: str | None = Field(default=None, max_length=120)
    reason: str | None = Field(default=None, max_length=2000)


class ChangeSetResponse(BaseModel):
    change_set_id: str
    review_id: str
    experiment_id: str
    product_id: str
    change_type: str
    status: str
    expected: dict[str, Any]
    proposed: dict[str, Any]
    created_by: str
    approver: str | None
    approval_reason: str | None
    created_at: datetime
    decided_at: datetime | None


class RolloutApplyRequest(BaseModel):
    actor: str | None = Field(default=None, max_length=120)


class RolloutResponse(BaseModel):
    rollout_id: str
    change_set_id: str
    status: str
    actor: str
    before: dict[str, Any]
    after: dict[str, Any]
    applied_at: datetime


class RolloutMonitorCurrencySummary(BaseModel):
    currency: str
    sales_minor_units: int
    refunds_minor_units: int
    net_revenue_minor_units: int


class RolloutMonitorResponse(BaseModel):
    rollout_id: str
    rollout_status: str
    monitoring_status: Literal[
        "state_consistent",
        "state_drift",
    ]
    automatic_rollback: Literal[False] = False
    expected_state: dict[str, Any]
    current_state: dict[str, Any]
    metrics_window_start: datetime
    metrics_window_end: datetime | None
    impressions: int
    clicks: int
    purchases: int
    refunds: int
    ctr: float
    cvr: float
    currencies: list[RolloutMonitorCurrencySummary]


class RollbackRequest(BaseModel):
    actor: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=2000)


class RollbackResponse(BaseModel):
    rollback_id: str
    rollout_id: str
    actor: str
    reason: str
    before: dict[str, Any]
    after: dict[str, Any]
    rolled_back_at: datetime


class CredentialIssueRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=120)
    roles: list[str] = Field(min_length=1, max_length=20)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


class CredentialResponse(BaseModel):
    credential_id: str
    subject: str
    roles: list[str]
    key_id: str
    token_type: Literal["Bearer"]
    access_token: str
    issued_at: datetime
    expires_at: datetime


class CredentialRevokeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class CredentialStatusResponse(BaseModel):
    credential_id: str
    subject: str
    roles: list[str]
    key_id: str
    issued_by: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revoked_by: str | None
    revoke_reason: str | None
    active: bool


class SigningKeyStatusResponse(BaseModel):
    active_key_id: str
    configured_key_ids: list[str]
    auth_mode: str
    max_ttl_seconds: int


class AuditEventResponse(BaseModel):
    id: int
    job_id: str | None
    event_type: str
    actor: str | None
    payload: dict
    previous_hash: str
    hash_key_id: str
    event_hash: str
    created_at: datetime


class AuditAnchorReceiptResponse(BaseModel):
    receipt_id: str
    namespace: str
    anchor_id: str
    head_event_id: int | None
    head_hash: str
    head_state_hash: str
    head_hash_key_id: str
    requested_by: str
    anchored_at: datetime
    receipt_key_id: str
    receipt_signature: str


class AuditAnchorVerificationResponse(BaseModel):
    valid: bool
    status: Literal[
        "in_sync",
        "local_ahead",
        "rollback_detected",
        "external_anchor_missing",
        "local_chain_invalid",
        "anchor_mismatch",
    ]
    namespace: str
    anchor_id: str | None
    anchor_event_id: int | None
    local_event_id: int | None
    anchor_head_hash: str | None
    local_head_hash: str
    anchored_at: datetime | None
    reason: str | None


class AuditAnchorFreshnessResponse(BaseModel):
    fresh: bool
    verification_status: str
    anchor_event_id: int | None
    local_event_id: int | None
    unanchored_events: int
    anchored_at: datetime | None
    age_seconds: int | None
    max_age_seconds: int
    max_unanchored_events: int
    reason: str | None


class ProductionReadinessCheck(BaseModel):
    name: str
    ready: bool
    detail: str


class ProductionReadinessResponse(BaseModel):
    ready: bool
    checks: list[ProductionReadinessCheck]


class AuditIntegrityResponse(BaseModel):
    valid: bool
    checked_events: int
    head_event_id: int | None
    head_hash: str
    first_invalid_event_id: int | None
    reason: str | None



class OperationalRouteMetric(BaseModel):
    route: str
    requests: int
    errors: int
    average_duration_ms: float
    max_duration_ms: float


class OperationalAlertStatus(BaseModel):
    signal: str
    severity: Literal["warning", "critical"]
    count: int
    threshold: int
    triggered: bool


class OperationalStatusResponse(BaseModel):
    healthy: bool
    uptime_seconds: float
    requests_total: int
    status_classes: dict[str, int]
    errors_by_class: dict[str, int]
    incident_signals: dict[str, int]
    routes: list[OperationalRouteMetric]
    alerts: list[OperationalAlertStatus]
