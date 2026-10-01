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
