# Failure and Recovery Runbook

This runbook defines the expected safe behavior for dependency failures and the recovery sequence after each failure.

## 1. Verification provider interruption

Expected behavior:

- without current trusted age and consent verification records, content generation is blocked when `REQUIRE_TRUSTED_VERIFICATION=true`
- no unverified content should advance through policy/publish as if verification had succeeded

Recovery:

1. restore the provider delivery path
2. accept signed `verification.verified` events
3. confirm the verification IDs are active
4. retry content generation using the same creator reference and verification IDs
5. continue policy and approval only after successful trusted resolution

## 2. Webhook signing-key mismatch during rotation

Expected behavior:

- a request naming a retired or unknown key ID returns HTTP 401
- the failed authentication attempt must not reserve the provider event ID

Recovery:

1. verify the provider and application agree on the active `kid`
2. sign the original event bytes with an accepted key
3. resend using the same provider event ID
4. confirm the first authenticated delivery returns `duplicate=false`
5. confirm later exact retries return `duplicate=true`

This makes key-rotation mistakes recoverable without fabricating replacement event IDs.

## 3. External/WORM anchor outage

Expected behavior:

- anchor creation/lookup fails closed
- `GET /ready` returns HTTP 503
- fresh-anchor-gated rollout cannot proceed

Recovery:

1. restore network/service access to the WORM anchor service
2. verify the configured bearer credential and receipt-verification key
3. create a fresh anchor
4. call `GET /v1/audit/anchors/verify`
5. call `GET /ready`
6. resume rollout only after readiness is green

Do not disable anchor freshness enforcement merely to bypass an outage.

## 4. Database rollback / snapshot restore

Expected behavior:

- the local HMAC audit chain may still be internally valid after a full restore to an older legitimate snapshot
- the latest external WORM anchor remains ahead
- readiness reports rollback detection and stays unavailable

Recovery:

1. stop production mutations
2. preserve the restored database and external anchor evidence
3. identify the intended recovery point
4. restore/replay missing authoritative state
5. verify local audit-chain integrity
6. verify external anchor consistency
7. write a new external anchor only after the recovered local chain is correct
8. return service to ready state

Do not overwrite or delete the newer external anchor to make the restored DB appear current.

## 5. Application process restart

Process-local counters and latency summaries reset on restart. Security state, idempotency ledgers, audit history, rollout state, verification state, and credentials remain database-backed.

After restart:

1. run migration/readiness checks
2. verify external anchor freshness
3. retry in-flight idempotent provider events or rollout requests using their original identifiers
4. confirm the existing DB-backed result is returned rather than duplicated

## 6. Concurrent production mutations

Production uses a row-locking database and optimistic `state_version` checks.

Expected behavior:

- PostgreSQL `SELECT ... FOR UPDATE` serializes competing writers for the same mutable state
- stale optimistic writers receive HTTP 409
- unique constraints converge exact idempotent create/apply/rollback races onto one resource

On repeated concurrency conflicts, investigate the callers rather than increasing retry aggressiveness blindly.

## Verification checklist

Before restoring production traffic, verify:

```text
GET /health
GET /ready
GET /v1/ops/status
GET /v1/audit/integrity
GET /v1/audit/anchors/verify
GET /v1/audit/anchors/freshness
```

A recovery is incomplete if health is green but readiness, audit integrity, or external anchor verification is not.
