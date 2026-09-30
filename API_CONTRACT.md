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

Request:

```json
{
  "campaign_type": "members_only_release",
  "target_segment": "subscribers",
  "price_cents": 1500,
  "creator_age": 21,
  "age_verified": true,
  "consent_verified": true,
  "depicts_real_person": false,
  "real_person_consent_verified": false
}
```

## POST /v1/policy/evaluate

When `job_id` is provided, the result is persisted and an audit event is recorded.

A job with a failed or missing policy result cannot enter approval.

## POST /v1/approvals

Request:

```json
{
  "job_id": "job_123",
  "required": true
}
```

Response:

```json
{
  "job_id": "job_123",
  "status": "pending_review",
  "required": true,
  "reviewer": null,
  "reason": null,
  "created_at": "2026-10-01T00:00:00Z",
  "decided_at": null
}
```

The call is idempotent for an existing approval record.

## GET /v1/approvals/{job_id}

Returns current approval state.

## POST /v1/approvals/{job_id}/approve

Request:

```json
{
  "reviewer": "reviewer-1",
  "reason": "verification complete"
}
```

## POST /v1/approvals/{job_id}/reject

Request:

```json
{
  "reviewer": "reviewer-2",
  "reason": "manual review failed"
}
```

## GET /v1/audit/{job_id}

Returns ordered audit events for the job.

Current event types:

- `job_created`
- `policy_evaluated`
- `approval_created`
- `approval_approved`
- `approval_rejected`

There is no audit-delete API.

## Database state

Current persisted entities:

- job
- policy result
- approval
- reviewer
- decision reason
- timestamps
- audit events

## Planned endpoints

- `POST /v1/publish`
- `POST /v1/products`
- `GET /v1/revenue`
- `POST /v1/events`
- `GET /v1/metrics?window=7d`
