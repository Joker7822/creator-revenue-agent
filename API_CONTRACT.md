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


## Change Set APIs

```text
POST /v1/change-sets
GET  /v1/change-sets/{change_set_id}
POST /v1/change-sets/{change_set_id}/approve
POST /v1/change-sets/{change_set_id}/reject
POST /v1/change-sets/{change_set_id}/apply
GET  /v1/rollouts/{rollout_id}
```

Change-set creation requires a persisted experiment review whose decision is `variant_preferred`.

The first executable change type is `product_price`, derived from a completed price-test experiment. The server reconstructs expected and proposed values from the experiment plan; callers cannot submit arbitrary production values.

Approval uses separation of duties: the approver cannot be the experiment-result reviewer or the change-set creator.

Apply uses optimistic concurrency. If the live product currency or price differs from the expected control state recorded in the change set, the API returns HTTP 409 and makes no change.

Rollout application is idempotent per change set.


## Rollout monitoring

```text
GET /v1/rollouts/{rollout_id}/monitor
```

Returns current-vs-expected production state plus descriptive metrics from rollout application time. If a rollback occurred, the metric window ends at the rollback timestamp.

`monitoring_status` is:

- `state_consistent`
- `state_drift`

Business metrics are descriptive only. The API does not automatically classify a rollout as successful or harmful and does not trigger automatic rollback.

## Rollback

```text
POST /v1/rollouts/{rollout_id}/rollback
GET  /v1/rollbacks/{rollback_id}
```

Rollback requires an explicit actor and non-empty reason. Before restoring state, the server checks that the current product state exactly matches the state applied by the rollout. Any intervening production change causes HTTP 409.

Rollback is idempotent per rollout and restores the persisted pre-rollout state.


## Service identity and RBAC

Bearer credentials map to server-configured service identities and roles.

Sensitive mutation endpoints require a specific role:

```text
approval decisions                  reviewer
optimizer decisions                 reviewer
experiment result review            reviewer
publish                             publisher
experiment lifecycle mutations      experiment_operator
change-set creation                  planner
change-set approval/rejection        release_manager
change-set apply                     rollout_operator
rollback                             incident_manager
```

An `admin` role may perform any protected role operation.

Identity-like fields sent in JSON are compatibility fields only for these protected endpoints. The server records the authenticated service subject in workflow records and audit events.

A valid authenticated service without the required role receives HTTP 403.


## Short-lived service credentials

```text
POST /v1/auth/credentials
GET  /v1/auth/credentials/{credential_id}
POST /v1/auth/credentials/{credential_id}/revoke
GET  /v1/auth/signing-keys
```

Credential issue requires `credential_admin` (or `admin`).

Issued JWT claims include:

- `iss`
- `aud`
- `sub`
- `roles`
- `iat`
- `exp`
- `jti`

JWT headers use `alg=HS256`, `typ=JWT`, and a configured `kid`.

The server validates signature, issuer, audience, lifetime, allowed roles, key status, persisted issuance record, and revocation state.

Revocation is immediate for credentials managed by the internal issuer. Signing-key rotation supports an overlap period where old and new `kid` values are both configured.


## Database schema lifecycle

Database schema is versioned with Alembic. API startup does not create or mutate tables.

Deployment order:

```text
backup
  -> alembic upgrade head
  -> start new API version
```

The API performs a startup revision check and refuses to serve with a database revision that is not the current Alembic head.


## Trusted verification

```text
POST /v1/verifications
GET  /v1/verifications/{verification_id}
POST /v1/verifications/{verification_id}/revoke
```

Creation and revocation require the `verification_writer` role.

Verification kinds:

- `age` — requires `age_years`
- `creator_consent`
- `real_person_consent`

A verification is usable only while its status is active, it is not revoked, it is not expired, its kind matches the requested use, and its `subject_ref` matches the job creator reference.

`POST /v1/content/generate` accepts:

- `creator_ref`
- `age_verification_id`
- `consent_verification_id`
- `real_person_consent_verification_id`

When trusted verification is required, policy and publication derive verification state from these server-managed records. Request booleans cannot upgrade the record state.

Revocation marks referencing jobs' persisted policy result as not allowed. Publish performs an additional current-state verification check, so an approval obtained before consent revocation cannot be used to publish afterward.


## Verification Provider webhook

```text
POST /v1/webhooks/verifications
```

This endpoint uses webhook HMAC authentication rather than the internal Bearer credential.

Headers:

- `X-Verification-Provider`
- `X-Verification-Event-Id`
- `X-Verification-Timestamp` — Unix seconds
- `X-Verification-Signature` — `v1=<HMAC-SHA256 hex>`

Canonical signed bytes:

```text
<provider>.<timestamp>.<event_id>.<raw request body>
```

Replay protection rejects timestamps outside `VERIFICATION_WEBHOOK_MAX_AGE_SECONDS` (300 seconds by default).

Idempotency is scoped by provider and event ID. An identical replay returns the persisted original result. The same event ID with a different body hash returns HTTP 409.

Payload event types are `verification.verified` and `verification.revoked`. Provider record references, subject references, and verification kinds must match before an existing record can be revoked.


## Verification webhook key rotation

Webhook requests should include:

```text
X-Verification-Key-Id: <kid>
```

With a key ID present, canonical signed bytes are:

```text
<provider>.<key_id>.<timestamp>.<event_id>.<raw request body>
```

`VERIFICATION_WEBHOOK_KEYS_JSON` maps each provider to one or more accepted key IDs. Removing a key ID immediately causes requests naming that key to fail authentication.

The event ledger records the key ID that authenticated the original delivery. An exact duplicate delivered later with another currently valid key still returns the original event result and its original recorded key ID.

```text
GET /v1/auth/verification-webhook-keys
```

returns only provider names and accepted key IDs, never secret material, and requires `credential_admin`.

The legacy no-key-ID canonical form may be enabled only for migration with `VERIFICATION_WEBHOOK_REQUIRE_KEY_ID=false` and exactly one accepted key for that provider.


## Audit integrity

```text
GET /v1/audit/integrity
```

Audit events expose `previous_hash`, `hash_key_id`, and `event_hash`.

New events are authenticated with HMAC-SHA256 using the key selected by `AUDIT_HASH_ACTIVE_KID`. The server also authenticates the persisted chain head.

The integrity response includes:

- `valid`
- `checked_events`
- `head_event_id`
- `head_hash`
- `first_invalid_event_id`
- `reason`

Detected failure classes include event content modification, broken previous-hash links, missing/unknown historical HMAC keys, missing chain state, chain-head mismatch, and chain-state MAC mismatch.

Rows created before HMAC chaining are migrated under `legacy-sha256-v1`.


## External audit anchor

```text
POST /v1/audit/anchors
GET  /v1/audit/anchors/verify
```

`POST /v1/audit/anchors` requires `audit_anchor_operator`. It refuses to anchor if the local HMAC audit chain is invalid.

The configured external service receives an idempotent anchor containing:

- namespace
- deterministic anchor ID
- head event ID
- head event hash
- authenticated chain-state hash
- audit hash key ID
- authenticated service subject requesting the anchor

The returned WORM receipt must be signed by a trusted receipt key.

Verification always queries the external service for the latest receipt; it does not treat the local receipt table as authoritative. This allows restoration of the application database to an older internally valid snapshot to be detected when the external anchor is ahead.


## Production readiness

```text
GET /ready
```

This endpoint is intended for deployment/orchestrator readiness checks. It returns HTTP 200 when ready and HTTP 503 otherwise.

The response contains a top-level `ready` boolean and named checks for:

- current Alembic database revision
- JWT service authentication mode and signing-key validity
- trusted verification enforcement
- verification-webhook key-ID enforcement
- audit HMAC key configuration
- local audit-chain integrity
- external audit-anchor freshness

The response exposes status and identifiers needed for diagnosis but never secret key material.

## Audit-anchor freshness

```text
GET /v1/audit/anchors/freshness
```

Freshness requires the latest external anchor to pass rollback/integrity verification, be no older than `AUDIT_ANCHOR_MAX_AGE_SECONDS`, and be no more than `AUDIT_ANCHOR_MAX_UNANCHORED_EVENTS` behind the local chain.

When `ENFORCE_AUDIT_ANCHOR_FRESHNESS_ON_ROLLOUT=true`, `POST /v1/change-sets/{change_set_id}/apply` returns HTTP 409 instead of modifying production state when the freshness gate fails.
