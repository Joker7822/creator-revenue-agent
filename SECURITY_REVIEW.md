# Final Security Review

This document records the release-gating security properties currently enforced by code and CI.

## Identity and authorization

- Production uses JWT-only service authentication.
- Static service identities and legacy bearer-token material are rejected by the production release gate.
- Short-lived credentials remain revocable through persisted issuance records.
- High-risk write surfaces are role-protected and continuously tested against a read-only principal.
- Request-body actor/reviewer/publisher fields are never authoritative for protected mutations.

## Verification and content safety

- Trusted verification is required in production.
- Age and consent state are server-authoritative and resolved from persisted verification records.
- Verification webhook key IDs are required.
- Provider webhook signatures, replay windows, event idempotency, body-size limits, and rate limits are enforced.
- Revoked or stale verification cannot be used to publish.

## Billing integrity

- Sales must match the current product price.
- Refunds must reference an original sale.
- Refund product/currency must match the original sale.
- Aggregate refunds cannot exceed the original sale.
- Historical unlinked refunds fail closed until reconciled.
- Billing mutations require the dedicated billing-writer role and rate limit.

## Production state changes

- Approval, optimizer, experiment, change-set, product, rollout, and rollback state transitions use optimistic versions.
- Production databases must support row-level locking.
- Rollout requires reviewed evidence and separation of duties.
- Rollout freshness depends on a valid external WORM audit anchor.
- Stale or conflicting production state blocks mutation.

## Audit integrity

- Audit events are HMAC chained.
- Chain head state is separately authenticated.
- External WORM receipts detect restoration to an older internally valid database snapshot.
- Historical audit and receipt verification keys must remain available for verification.

## Abuse resistance

Production release gating constrains:

- maximum request body size
- billing mutation rate
- credential administration rate
- rollout mutation rate
- verification webhook rate

Process-local controls are defense in depth. Production ingress should also provide distributed rate limiting, DDoS protection, and connection limits.

## Deployment

- Production requires PostgreSQL.
- Migrations must be at Alembic head before release.
- Containers run as non-root with a read-only root filesystem in the production deployment example.
- Secrets are injected outside source control, including mounted secret-file support.
- Backup/restore is rehearsed in CI against PostgreSQL.
- External audit anchoring requires HTTPS.

## Release gate

Run:

```bash
python -m api_server.release_gate
```

The command fails the release when a production invariant or database revision check fails.

CI also runs a production-identity E2E flow using role-specific short-lived JWTs:

```text
Trusted Verification
        ↓
Policy
        ↓
Human Review
        ↓
Publish
        ↓
Product
        ↓
Sale + linked Refund
        ↓
Revenue
        ↓
Audit Integrity
```

## Residual operational risks

The remaining risks are primarily infrastructure/operations rather than missing application controls:

- distributed ingress/WAF rate limiting is external to this repository
- managed secret rotation and HSM/KMS-backed asymmetric service identity remain deployment choices
- backup retention, encryption, and restore objectives depend on the production platform
- WORM durability and administrative independence depend on the external anchor provider
- operational metrics are process-local until exported to a durable monitoring backend

These items should be validated in the target production environment before accepting real traffic.
