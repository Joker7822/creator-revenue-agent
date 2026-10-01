# Proprietary API Contract

This document defines the internal API contract used by `creator-revenue-agent`.

## Authentication

Protected endpoints require a bearer service token.

## Workflow APIs

```text
POST /v1/content/generate
POST /v1/policy/evaluate
POST /v1/approvals
GET  /v1/approvals/{job_id}
POST /v1/approvals/{job_id}/approve
POST /v1/approvals/{job_id}/reject
POST /v1/publish
GET  /v1/publications/{job_id}
```

## Billing APIs

```text
POST /v1/products
GET  /v1/products/{product_id}
POST /v1/transactions
GET  /v1/revenue
```

Transactions are the source of truth for purchases, refunds, and revenue.

## POST /v1/events

Records high-volume funnel events.

Request:

```json
{
  "event_id": "evt_123",
  "publication_id": "pub_123",
  "event_type": "impression",
  "metadata": {
    "source": "feed"
  }
}
```

Supported event types:

- `impression`
- `click`

Rules:

- publication must exist and be published
- `event_id` is the idempotency key
- identical replay returns the existing event
- same ID with different data returns HTTP 409
- event metadata is stored as JSON
- engagement events are not copied to the compliance audit table

## GET /v1/metrics

Examples:

```text
GET /v1/metrics?window=7d
GET /v1/metrics?window=30d&publication_id=pub_123
```

Response:

```json
{
  "window": "7d",
  "since": "2026-09-24T00:00:00Z",
  "publication_id": "pub_123",
  "impressions": 10,
  "clicks": 4,
  "purchases": 2,
  "refunds": 1,
  "ctr": 0.4,
  "cvr": 0.5,
  "currencies": [
    {
      "currency": "JPY",
      "sales_count": 2,
      "refund_count": 1,
      "sales_minor_units": 3000,
      "refunds_minor_units": 500,
      "net_revenue_minor_units": 2500
    }
  ]
}
```

Definitions:

```text
CTR = clicks / impressions
CVR = purchases / clicks
```

When the denominator is zero, the metric is `0.0`.

Revenue remains separated by currency. No implicit FX conversion occurs.

## Audit API

```text
GET /v1/audit/{job_id}
```

## Planned next step

Optimization layer using historical metrics while keeping policy and approval gates authoritative.


## Experiment APIs

```text
POST /v1/experiments
GET  /v1/experiments/{experiment_id}
POST /v1/experiments/{experiment_id}/start
POST /v1/experiments/{experiment_id}/complete
POST /v1/experiments/{experiment_id}/cancel
```

Creation requires an approved optimizer proposal and an experimentable recommendation.

Supported experiment plan types:

- price test
- non-explicit teaser test
- posting-time test

Experiments are records/plans only. Starting one does not mutate product price, replace content, publish, or route live traffic.


## Experiment assignment

```text
POST /v1/experiments/{experiment_id}/assignments
```

Request:

```json
{
  "subject_key": "opaque-pseudonymous-key"
}
```

The raw subject key is not persisted. Assignment is deterministic and returns either `control` or `variant`.

## Experiment events

```text
POST /v1/experiments/{experiment_id}/events
```

Supported event types:

- `impression`
- `click`

Event IDs are idempotency keys.

## Experiment transaction linkage

```text
POST /v1/experiments/{experiment_id}/transactions
```

The request references an existing Billing API transaction and an experiment assignment. Transaction product must match the experiment product.

## Experiment results

```text
GET /v1/experiments/{experiment_id}/results
```

Returns control/variant descriptive metrics and per-currency revenue deltas. The API does not automatically declare a winner.

Evaluation status:

- `insufficient_data` while either arm has fewer than 20 clicks
- `ready_for_manual_review` otherwise


## Experiment statistics

```text
GET /v1/experiments/{experiment_id}/statistics
```

Returns 95% Wilson confidence intervals for CTR and CVR, two-sided two-proportion z-test p-values, and explicit readiness gates.

Default gates:

```text
EXPERIMENT_MIN_RUNTIME_HOURS=24
EXPERIMENT_MIN_ASSIGNMENTS_PER_ARM=100
EXPERIMENT_MIN_IMPRESSIONS_PER_ARM=100
EXPERIMENT_MIN_CLICKS_PER_ARM=20
```

Experiment completion is blocked with HTTP 409 until all gates pass.

The statistics response always leaves `winner` null and requires human review.

## Experiment result review

```text
POST /v1/experiments/{experiment_id}/reviews
GET  /v1/experiments/{experiment_id}/review
```

Allowed decisions:

- `control_preferred`
- `variant_preferred`
- `inconclusive`

Review requires a completed experiment and persists the statistical snapshot used for the decision. It does not change production configuration.


## Trust boundary rules

When `POST /v1/policy/evaluate` includes `job_id`, the server evaluates the job's persisted verification facts. Request fields such as `creator_age`, `age_verified`, and consent booleans are not trusted to override the job.

For `POST /v1/approvals`, `required` is only a request hint. If server configuration has `REQUIRE_HUMAN_REVIEW=true`, the effective value is always true and the initial status is `pending_review`.
