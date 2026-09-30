# Proprietary API Contract

This document defines the internal API contract used by `creator-revenue-agent`.

## Authentication

Protected endpoints require:

```http
Authorization: Bearer <INTERNAL_API_TOKEN>
Content-Type: application/json
```

The orchestrator uses `CUSTOM_API_TOKEN` when calling the API. Production deployments should prefer short-lived service credentials, HMAC request signing, or mTLS over a long-lived static token.

## GET /health

No authentication is required.

Response:

```json
{
  "status": "ok"
}
```

## POST /v1/content/generate

**Current scope:** generate non-explicit campaign metadata only. This endpoint does not generate adult media assets.

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

Response:

```json
{
  "job_id": "job_...",
  "title": "Members Only Release campaign",
  "teaser": "New members-only release for subscribers.",
  "price_cents": 1500,
  "creator_age": 21,
  "age_verified": true,
  "consent_verified": true,
  "depicts_real_person": false,
  "real_person_consent_verified": false,
  "asset_ref": null
}
```

The verification fields are part of the current MVP contract. In production they must come from a trusted internal verification system rather than self-asserted client input.

## POST /v1/policy/evaluate

Request:

```json
{
  "job_id": "job_123",
  "creator_age": 21,
  "age_verified": true,
  "consent_verified": true,
  "depicts_real_person": false,
  "real_person_consent_verified": false,
  "asset_ref": null
}
```

Allowed response:

```json
{
  "allowed": true,
  "reasons": []
}
```

Rejected example:

```json
{
  "allowed": false,
  "reasons": [
    "adult_age_not_verified"
  ]
}
```

Current rejection reasons include:

- `adult_age_not_verified`
- `age_verification_required`
- `creator_consent_required`
- `real_person_consent_required`
- `github_asset_storage_not_allowed`

## Planned endpoints

### POST /v1/approvals
Create a human-review item.

### GET /v1/approvals/{job_id}
Read approval state.

### POST /v1/publish
Publish an approved job.

### POST /v1/products
Create an internal billable product or offer.

### GET /v1/revenue
Return normalized proprietary transaction/revenue data.

### POST /v1/events
Record analytics and conversion events.

### GET /v1/metrics?window=7d
Return aggregate performance metrics.
