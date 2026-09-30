# Proprietary API Contract

This document defines the internal API contract used by `creator-revenue-agent`.

## Authentication

Protected endpoints require:

```http
Authorization: Bearer <INTERNAL_API_TOKEN>
Content-Type: application/json
```

## GET /health

Response:

```json
{
  "status": "ok"
}
```

## POST /v1/content/generate

Current scope: non-explicit campaign metadata only.

The resulting job is persisted before the API returns.

## POST /v1/policy/evaluate

When `job_id` is provided, the result is persisted and an audit event is recorded.

A job with a failed or missing policy result cannot enter approval or publication.

## Approval endpoints

- `POST /v1/approvals`
- `GET /v1/approvals/{job_id}`
- `POST /v1/approvals/{job_id}/approve`
- `POST /v1/approvals/{job_id}/reject`

A publication requires `approval.status == approved`.

## POST /v1/publish

Creates the internal publication record only after policy and approval gates pass.

Request:

```json
{
  "job_id": "job_123",
  "destination": "internal-storefront",
  "publisher": "agent-1"
}
```

Response:

```json
{
  "publication_id": "pub_...",
  "job_id": "job_123",
  "status": "published",
  "destination": "internal-storefront",
  "publisher": "agent-1",
  "published_at": "2026-10-01T00:00:00Z"
}
```

Rules:

- unknown job -> HTTP 404
- policy not allowed/missing -> HTTP 409
- approval missing/pending/rejected -> HTTP 409
- approved -> publication created
- repeated call for the same job -> same publication returned

The current endpoint records internal publication state. It does not yet deliver explicit media to an external platform.

## GET /v1/publications/{job_id}

Returns the existing publication for the job or HTTP 404.

## GET /v1/audit/{job_id}

Returns ordered audit events for the job.

Current event types include:

- `job_created`
- `policy_evaluated`
- `approval_created`
- `approval_approved`
- `approval_rejected`
- `publication_published`

## Database state

Persisted entities:

- job
- policy result
- approval
- reviewer
- publication
- timestamps
- audit events

## Planned endpoints

- `POST /v1/products`
- `GET /v1/revenue`
- `POST /v1/events`
- `GET /v1/metrics?window=7d`
