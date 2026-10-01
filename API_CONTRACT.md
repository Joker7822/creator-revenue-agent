# Proprietary API Contract

This document defines the internal API contract used by `creator-revenue-agent`.

## Authentication

Protected endpoints require a bearer service token.

## Workflow endpoints

```text
POST /v1/content/generate
POST /v1/policy/evaluate
POST /v1/approvals
GET  /v1/approvals/{job_id}
POST /v1/approvals/{job_id}/approve
POST /v1/approvals/{job_id}/reject
POST /v1/publish
GET  /v1/publications/{job_id}
GET  /v1/audit/{job_id}
```

## POST /v1/products

Creates a billable product for a published publication.

Request:

```json
{
  "publication_id": "pub_123",
  "name": "Premium release",
  "currency": "JPY",
  "price_minor_units": 1500
}
```

Rules:

- publication must exist and be published
- currency is normalized to uppercase
- monetary values are integers in currency minor units

## GET /v1/products/{product_id}

Returns a product.

## POST /v1/transactions

Records a proprietary billing event.

Request:

```json
{
  "transaction_id": "tx_order_123",
  "product_id": "prod_123",
  "kind": "sale",
  "amount_minor_units": 1500,
  "currency": "JPY",
  "occurred_at": "2026-10-01T00:00:00Z"
}
```

`kind` is either `sale` or `refund`.

Rules:

- product must exist and be active
- transaction currency must equal product currency
- `transaction_id` is the idempotency key
- replaying identical data returns the existing transaction
- replaying the same ID with different data returns HTTP 409

## GET /v1/revenue

Optional query:

```text
?since=2026-10-01T00:00:00Z
```

Response:

```json
{
  "since": null,
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

Different currencies are never automatically converted or summed.

## Audit events

Billing adds:

- `product_created`
- `transaction_recorded`

## Planned next step

Analytics endpoints:

- `POST /v1/events`
- `GET /v1/metrics?window=7d`
