# Proprietary API Contract

All endpoints are owned and operated by the project. The examples below define the minimum contract expected by `creator-revenue-agent`.

## Authentication

Default starter authentication:

```http
Authorization: Bearer <CUSTOM_API_TOKEN>
Content-Type: application/json
```

For production, short-lived service credentials, HMAC signatures, or mTLS are preferable to a long-lived static token.

## POST /v1/content/generate

Request:

```json
{
  "campaign_type": "members_only_release",
  "target_segment": "subscribers",
  "price_cents": 1500
}
```

Response:

```json
{
  "job_id": "job_123",
  "creator_age": 21,
  "age_verified": true,
  "consent_verified": true,
  "depicts_real_person": false,
  "real_person_consent_verified": false,
  "asset_ref": "asset_abc"
}
```

`asset_ref` must refer to storage outside GitHub.

## POST /v1/policy/evaluate

Response:

```json
{
  "allowed": true,
  "reasons": []
}
```

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
  "status": "pending_review"
}
```

## GET /v1/approvals/{job_id}

Response:

```json
{
  "job_id": "job_123",
  "status": "approved"
}
```

## POST /v1/publish

Request:

```json
{
  "job_id": "job_123"
}
```

Response:

```json
{
  "job_id": "job_123",
  "status": "published",
  "publication_id": "pub_456"
}
```

## POST /v1/products

Creates an internal billable product or offer.

## GET /v1/revenue

Returns normalized proprietary transaction/revenue data.

## POST /v1/events

Records analytics and conversion events.

## GET /v1/metrics?window=7d

Response:

```json
{
  "window": "7d",
  "impressions": 10000,
  "conversions": 250,
  "revenue_cents": 375000
}
```
