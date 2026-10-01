# creator-revenue-agent

AI-powered creator revenue orchestration built around proprietary APIs.

## Scope

This repository contains the orchestration layer, proprietary API server, persistence layer, CI/CD, API contracts, tests, safety controls, billing, and analytics.

GitHub is used for source code and automation only. Do not commit generated adult media, identity documents, consent evidence, payment data, or secrets.

## Architecture

```text
GitHub Actions
    |
    v
Creator Revenue Agent
    |
    +--> Local Guardrails
    +--> Proprietary API
           +--> Content Metadata API
           +--> Policy API
           +--> Approval API
           +--> Publishing API
           +--> Billing API
           +--> Analytics API
           +--> Audit API
    |
    +--> SQL database
```

## Current implementation

Implemented:

- content metadata and policy APIs
- human approval workflow
- gated/idempotent publishing
- products and proprietary billing transaction ingestion
- revenue aggregation by currency
- analytics event ingestion
- CTR / CVR / purchase / refund / revenue metrics
- audit trail
- bearer-token service authentication
- SQLite development database / SQLAlchemy abstraction
- Alembic versioned database migrations
- FastAPI / Docker / pytest / GitHub Actions CI

## Analytics model

High-volume engagement events are stored separately from the compliance audit log.

```text
POST /v1/events
  impression
  click
```

Purchases and refunds are not duplicated as analytics events. The Billing API is the source of truth:

```text
POST /v1/transactions
  sale
  refund
```

`GET /v1/metrics` joins both sources.

Metrics include:

- impressions
- clicks
- purchases
- refunds
- CTR = clicks / impressions
- CVR = purchases / clicks
- net revenue grouped by currency

Different currencies are never automatically converted or summed.

## Example

```text
10 impressions
 4 clicks
 2 purchases
 1 refund

CTR = 4 / 10 = 0.40
CVR = 2 / 4  = 0.50
```

## Analytics endpoints

```text
POST /v1/events
GET  /v1/metrics?window=7d
GET  /v1/metrics?window=30d&publication_id=pub_...
```

Supported window syntax:

- `24h`
- `7d`
- `30d`

## Core flow

```text
Metadata
   |
Policy
   |
Approval
   |
Publish
   |
Product
   |
+--+-------------------+
|                      |
Engagement events   Transactions
|                      |
+----------+-----------+
           |
        Metrics
           |
     Optimizer
        |
   Human Review
        |
     Experiment
```

## Database tables

- `jobs`
- `approvals`
- `publications`
- `products`
- `transactions`
- `analytics_events`
- `audit_events`

Schema changes are managed with Alembic. For production, use a managed SQL database and run migrations as a dedicated release step before deployment.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn api_server.main:app --reload
```

Run tests:

```bash
pytest -q
```

## Safety baseline

- Adults only; reject minors and age-ambiguous cases.
- Require positive age verification and documented consent.
- Real-person sexual depictions require separately verified consent.
- Publishing requires both policy success and explicit approval.
- Explicit assets must live outside GitHub.
- Identity, consent and payment secrets must not be committed.

## Repository

`Joker7822/creator-revenue-agent`


## Experiment layer

Approved optimizer recommendations can be converted into experiment records.

```text
approved proposal
      |
    draft
      |
   running
    /   \
completed cancelled
```

Experiment state changes do not automatically change price, content, publishing, or traffic routing.


## Experiment assignment and evaluation

Running experiments support deterministic control/variant assignment, experiment-specific impression/click events, Billing transaction linkage, and arm-level results.

The service stores only an experiment-scoped SHA-256 subject hash, not the raw assignment key.

```text
running experiment
      |
  assignment
   /      \
control  variant
   |        |
events + billing links
   \        /
      results
        |
 manual review
```

Results never auto-select a winner or mutate production configuration.


## Statistical experiment review

Experiment results now include a separate statistical-readiness layer.

Default completion gates:

```text
minimum runtime:          24 hours
minimum assignments/arm: 100
minimum impressions/arm: 100
minimum clicks/arm:       20
```

The statistics endpoint returns 95% Wilson confidence intervals for CTR/CVR and two-sided two-proportion z-test p-values. Statistical output never auto-selects a winner.

An experiment cannot be completed until all readiness gates pass. After completion, a human reviewer records one of:

- `control_preferred`
- `variant_preferred`
- `inconclusive`

A review stores a statistics snapshot but does not mutate product price, content, or publishing state.


## Trust boundary hardening

For persisted jobs, policy evaluation uses the verification facts already stored with the job. Caller-supplied age or consent booleans on a `job_id` policy request cannot upgrade the stored verification state.

When `REQUIRE_HUMAN_REVIEW=true`, an approval request cannot disable review with `required=false`. The server derives the effective requirement and keeps the approval in `pending_review` until an explicit approve action is recorded.


## Change Set and Rollout

A statistically reviewed experiment does not directly modify production.

For the first rollout-capable MVP, only approved price-test variants are executable:

```text
completed experiment
      |
variant_preferred review
      |
change set: pending_approval
      |
separate approver
      |
approved
      |
optimistic state check
      |
rollout applied
```

Safety rules:

- only `variant_preferred` reviews can produce a change set
- only price-test experiments are executable in this version
- proposed price movement is revalidated to stay within 10%
- the change-set approver must differ from both the experiment-result reviewer and the change-set creator
- apply checks that the live product price still matches the experiment control value
- duplicate apply calls return the same rollout record
- creative and posting-time recommendations remain non-executable until separate production adapters exist


## Rollout monitoring and rollback

Applied rollouts can be monitored without automatically deciding whether business performance is good or bad.

```text
GET  /v1/rollouts/{rollout_id}/monitor
POST /v1/rollouts/{rollout_id}/rollback
GET  /v1/rollbacks/{rollback_id}
```

The monitor reports:

- whether the current production state still matches the expected rollout state
- post-rollout impressions and clicks
- purchases and refunds
- CTR and CVR
- revenue separated by currency

The monitor never auto-rolls back. A rollback requires an explicit actor and reason.

Rollback uses another optimistic state check. If production has changed since the rollout, rollback returns HTTP 409 rather than overwriting the intervening change. A successful rollback restores the exact pre-rollout price and is idempotent.


## Service Identity and RBAC

Sensitive workflow mutations now derive the audit actor from the authenticated service identity rather than request JSON.

Configured roles:

- `reviewer`: approval decisions, optimizer decisions, experiment-result review
- `publisher`: publication
- `experiment_operator`: create/start/complete/cancel experiments
- `planner`: create production change sets
- `release_manager`: approve/reject change sets
- `rollout_operator`: apply approved change sets
- `incident_manager`: rollback applied rollouts
- `admin`: emergency/test superset role

`reviewer`, `actor`, `owner`, `created_by`, and `publisher` fields remain accepted for backward-compatible request parsing, but protected endpoints ignore them for identity and use the authenticated principal.

Production should set `SERVICE_IDENTITIES_JSON` from a secret store and leave `ALLOW_LEGACY_ADMIN_TOKEN=false`.


## Short-lived signed service credentials

The internal API now supports short-lived HS256 JWT service credentials with a `kid`, `jti`, subject, roles, issued-at time, and expiration.

Credential administration endpoints:

```text
POST /v1/auth/credentials
GET  /v1/auth/credentials/{credential_id}
POST /v1/auth/credentials/{credential_id}/revoke
GET  /v1/auth/signing-keys
```

A `credential_admin` service can issue operational credentials. Credential TTL is capped by `SERVICE_JWT_MAX_TTL_SECONDS` (900 seconds by default). Issued credential metadata is persisted, but the bearer token itself is not stored.

Rotation uses multiple configured signing keys:

1. add the new key while retaining the old key
2. set `SERVICE_JWT_ACTIVE_KID` to the new key
3. wait for old credentials to expire or revoke them
4. remove the retired key

During the overlap, credentials signed by either configured key remain valid. Removing a key immediately makes credentials signed by that key invalid.

Production should run `SERVICE_AUTH_MODE=jwt`. `hybrid` exists only for bootstrap/migration from static service tokens.


## Database migration workflow

Application import no longer calls `Base.metadata.create_all()`.

Use:

```bash
alembic upgrade head
alembic current
```

The API validates the Alembic revision during application lifespan startup and fails fast if the database is behind.

The baseline migration can adopt databases created by the earlier `create_all()` implementation without dropping existing tables. See `DATABASE_MIGRATIONS.md`.


## Trusted Verification Registry

Age and consent can now be sourced from server-managed verification records instead of caller-supplied booleans.

```text
Verification Provider
        |
verification_writer service
        |
Verification Record
  age / creator_consent / real_person_consent
        |
Job references record IDs
        |
Policy
        |
Publish-time recheck
```

Endpoints:

```text
POST /v1/verifications
GET  /v1/verifications/{verification_id}
POST /v1/verifications/{verification_id}/revoke
```

With `REQUIRE_TRUSTED_VERIFICATION=true`, new jobs must provide a `creator_ref`, an active age verification record, and an active creator-consent verification record. Real-person depictions additionally require a real-person-consent record.

Caller-provided `age_verified`, `consent_verified`, and `creator_age` values are replaced by the trusted record state when verification references are present.

Revoking a verification record invalidates the stored policy state of referencing jobs. Publication also rechecks the current record state immediately before publishing.

The registry stores provider/source metadata and opaque external record references only. Raw identity documents and consent evidence remain outside this repository and database.


## Signed Verification Provider Webhooks

External verification providers can submit trusted state through:

```text
POST /v1/webhooks/verifications
```

Required headers:

```text
X-Verification-Provider
X-Verification-Event-Id
X-Verification-Timestamp
X-Verification-Signature
```

The signature is HMAC-SHA256 over the exact raw request body:

```text
provider + "." + unix_timestamp + "." + event_id + "." + raw_body
```

The signature header format is `v1=<hex digest>`.

Webhook processing verifies the provider-specific secret, enforces a bounded timestamp window, limits request body size, and persists a unique `(provider, event_id)` ledger entry.

An exact retry returns the original result with `duplicate=true`. Reusing an event ID with a different payload returns HTTP 409.

Supported events:

- `verification.verified`
- `verification.revoked`

The verification mutation and webhook event ledger are committed in one transaction, including concurrent duplicate handling.


## Verification webhook key rotation

Verification webhook signing now supports a provider-specific key ring selected by `X-Verification-Key-Id`.

Production configuration uses:

```text
VERIFICATION_WEBHOOK_KEYS_JSON={
  "provider-a": {
    "2026-09-retiring": "...",
    "2026-10-current": "..."
  }
}
VERIFICATION_WEBHOOK_REQUIRE_KEY_ID=true
```

The signed bytes are:

```text
provider + "." + key_id + "." + unix_timestamp + "." + event_id + "." + raw_body
```

Rotation sequence:

1. add the new key ID while retaining the old key
2. update the provider to sign with the new key ID
3. confirm new-key deliveries
4. remove the old key from configuration

Both configured keys are accepted during the overlap. Once the old key is removed, requests naming it receive HTTP 401.

Accepted key IDs can be inspected without exposing secrets:

```text
GET /v1/auth/verification-webhook-keys
```

This endpoint requires `credential_admin`.

For a temporary migration from the pre-`kid` signature format, set `VERIFICATION_WEBHOOK_REQUIRE_KEY_ID=false` while exactly one key is configured. The steady-state production setting should be `true`.


## Tamper-evident audit chain

Compliance audit events are chained globally in insertion order.

Each new event stores:

```text
previous_hash
hash_key_id
event_hash
```

New events use HMAC-SHA256 with a deployment secret selected by `AUDIT_HASH_ACTIVE_KID`. The HMAC covers event ID, job ID, event type, actor, canonical payload JSON, timestamp, previous hash, and key ID.

The chain head is stored separately with its own HMAC over the final event ID and final event hash. This detects ordinary row edits, middle-row deletion, and tail deletion where an attacker changes only database contents but does not possess the audit HMAC key.

Integrity can be checked with:

```text
GET /v1/audit/integrity
```

Existing audit rows predating this feature are migrated as `legacy-sha256-v1`; new rows use the configured HMAC key.

Retired audit verification keys must remain available if historical HMAC-protected events used them. A database rollback to an earlier internally consistent snapshot is outside the guarantees of an in-database chain and should be addressed with an external/WORM anchor.


## External / WORM audit anchors

The audit chain can now be anchored outside the application database.

```text
POST /v1/audit/anchors
GET  /v1/audit/anchors/verify
```

Anchor creation requires the `audit_anchor_operator` role.

The application sends the current authenticated audit-chain head to a configured append-only/WORM service. The external service returns a signed receipt. Receipt signatures are verified using `AUDIT_ANCHOR_RECEIPT_KEYS_JSON` before a receipt is accepted.

Rollback verification compares the latest external anchor with the local audit chain:

- external and local heads equal -> `in_sync`
- local chain extends the anchored prefix -> `local_ahead`
- external anchor is ahead of local DB -> `rollback_detected`
- anchored event/hash no longer matches local history -> invalid

Local `audit_anchor_receipts` rows are operational records only. The external WORM service is the rollback-detection source of truth.

See `AUDIT_ANCHOR.md` for the proprietary anchor-service contract and scheduling guidance.


## Production readiness and anchor freshness

Two operational checks are available:

```text
GET /ready
GET /v1/audit/anchors/freshness
```

`/ready` returns HTTP 200 only when all production-safety checks pass; otherwise it returns HTTP 503 with per-check status. It verifies the Alembic revision, JWT service authentication configuration, trusted-verification enforcement, verification-webhook key configuration, audit HMAC configuration, local audit-chain integrity, and external audit-anchor freshness.

Anchor freshness is bounded by both time and audit-event gap:

```text
AUDIT_ANCHOR_MAX_AGE_SECONDS=900
AUDIT_ANCHOR_MAX_UNANCHORED_EVENTS=100
```

Production rollout additionally enforces:

```text
ENFORCE_AUDIT_ANCHOR_FRESHNESS_ON_ROLLOUT=true
```

When enabled, an approved change set cannot be applied if the external anchor is missing, invalid, stale, behind by too many events, or indicates database rollback.


## Concurrent state transitions

Mutable workflow records now use optimistic `state_version` columns in addition to database row locks.

Protected state machines include human approvals, optimization proposal decisions, experiment lifecycle transitions, change-set decisions, product price state, and rollout state.

On row-locking databases, transition handlers acquire `SELECT ... FOR UPDATE` locks before validating and mutating state. SQLAlchemy also emits version-qualified updates so a stale writer that bypasses or races the lock is rejected.

Production readiness includes a `database_concurrency` check. Production should keep:

```text
PRODUCTION_REQUIRE_ROW_LOCKING_DATABASE=true
```

SQLite remains supported for local development and CI, where optimistic version checks still reject stale writes, but it is not considered a row-locking production database.


## Observability and incident diagnostics

Every HTTP request receives correlation headers:

```text
X-Request-ID
X-Trace-ID
```

A valid caller-provided `X-Request-ID` is preserved. W3C `traceparent` is accepted and its trace ID is propagated. Outbound audit-anchor calls carry the same request ID and trace ID.

Request completion is emitted as a structured JSON log event containing only bounded operational fields: method, route template, status code, duration, request ID, and trace ID. Authorization headers and request bodies are not logged.

Authenticated operators can inspect process-local operational telemetry:

```text
GET /v1/ops/status
```

The endpoint reports request/status counters, error classes, route-template latency summaries, incident signals, and configured alert thresholds. Dynamic resource IDs are never used as metric labels.

Incident signals include authentication rejection, verification-webhook rejection, audit-anchor failure, rollout apply failure, rollout state drift, rollback failure, readiness failure, and server/dependency 5xx.

These counters are process-local and reset on restart. Production should export the structured logs and status metrics to durable monitoring/alerting infrastructure.


## Failure and recovery validation

CI now exercises explicit recovery scenarios in addition to happy-path tests:

- trusted-verification provider absence blocks content creation until signed provider events arrive
- a retired webhook key is rejected without poisoning event idempotency; retrying the same event with the active key succeeds
- external/WORM anchor outage makes production readiness fail closed, then returns to ready after the dependency recovers and a fresh anchor is written
- process-local observability reset does not affect DB-backed webhook idempotency
- restoration to an older internally valid database snapshot is rejected by production readiness because the external anchor remains ahead
- a dedicated PostgreSQL CI job validates real `SELECT ... FOR UPDATE` serialization

Operational recovery procedures are documented in `RECOVERY_RUNBOOK.md`.


## Production deployment hardening

Production deployment guidance is in `DEPLOYMENT.md`.

Highlights:

- hardened non-root container image
- PostgreSQL-only production path with real row-lock CI coverage
- secret-manager / mounted `*_FILE` support
- preflight `python -m api_server.production_check`
- backup and restore scripts with checksum verification
- CI restore rehearsal against a separate PostgreSQL database
- read-only container filesystem and dropped Linux capabilities in the production Compose example

Do not place real secret files under source control. `secrets/`, `deploy/secrets/`, database dumps, and dump checksums are ignored.


## Billing integrity and abuse protection

Billing writes now require the dedicated `billing_writer` role (or `admin`).

New sales are accepted only when the transaction amount exactly matches the product's current price. Refunds must identify `original_sale_id`, must use the same product and currency as that sale, cannot predate the sale, and cumulative refunds cannot exceed the original sale amount.

Refund creation locks the original sale/product state on row-locking databases, preventing concurrent partial refunds from exceeding the sale total.

The API also applies bounded request bodies and process-local fixed-window limits to billing writes, credential mutation, rollout mutation, and verification webhooks. Production should additionally enforce distributed limits at the ingress/API-gateway layer.
