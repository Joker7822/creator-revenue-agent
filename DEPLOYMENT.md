# Production Deployment

This document describes the hardened production deployment path.

## Required architecture

Production should use:

- PostgreSQL as the transactional database
- an external secret manager exposed through environment variables or mounted secret files
- JWT-only service authentication
- trusted verification provider webhooks with key IDs
- external append-only/WORM audit anchoring
- a reverse proxy or load balancer providing TLS
- durable log/metric collection outside the application process

SQLite is for development and test only.

## Secret injection

Sensitive settings support either:

```text
SETTING=value
```

or:

```text
SETTING_FILE=/run/secrets/setting
```

Do not configure both forms for the same setting.

Production secret-file support covers:

```text
DATABASE_URL
SERVICE_IDENTITIES_JSON
SERVICE_JWT_KEYS_JSON
INTERNAL_API_TOKEN
CUSTOM_API_TOKEN
VERIFICATION_WEBHOOK_KEYS_JSON
VERIFICATION_WEBHOOK_SECRETS_JSON
AUDIT_HASH_KEYS_JSON
AUDIT_ANCHOR_TOKEN
AUDIT_ANCHOR_RECEIPT_KEYS_JSON
```

Mounted files are limited to 1 MiB, must be readable regular files, and must not be empty.

## Preflight configuration check

Before migrations or traffic cutover:

```bash
python -m api_server.production_check
```

The command exits nonzero when production safety requirements are not met. It checks the production environment, PostgreSQL URL, row-lock requirement, human-review and trusted-verification enforcement, JWT-only mode, key-ID requirements, rollout anchor enforcement, required secret sources, active JWT/audit key IDs, and HTTPS for the audit anchor.

It reports only configuration source names and key IDs, never secret contents.

## Container hardening

The production image:

- runs as UID/GID 10001
- has no login shell
- writes no Python bytecode
- includes an HTTP healthcheck
- does not run migrations on startup

The production Compose example additionally uses:

- read-only root filesystem
- `/tmp` tmpfs
- all Linux capabilities dropped
- `no-new-privileges`
- PID, CPU, and memory limits
- loopback-only example port binding
- mounted secret files

Build:

```bash
docker build -t creator-revenue-agent:production .
```

The example file is:

```text
deploy/docker-compose.production.example.yml
```

The `deploy/secrets/` directory is intentionally ignored by Git.

## Backup before release

Install PostgreSQL client utilities and run:

```bash
DATABASE_URL_FILE=/run/secrets/database_url \
  bash scripts/postgres_backup.sh /secure/backup/pre-release.dump
```

The backup script creates:

```text
pre-release.dump
pre-release.dump.sha256
```

with restrictive process umask.

Store backups outside the application host with encryption, retention, and access controls appropriate for production data.

## Restore verification

Restores are intentionally guarded:

```bash
DATABASE_URL_FILE=/run/secrets/restore_database_url \
RESTORE_CONFIRM=YES \
  bash scripts/postgres_restore.sh /secure/backup/pre-release.dump
```

When a checksum file exists it is verified before restore.

Never rehearse restore against the live production database. Restore into an isolated database and verify:

```bash
alembic current
python -m api_server.production_check
```

Then perform application-level integrity checks where external dependencies are available.

## Release sequence

Recommended order:

1. freeze or drain high-risk production mutations if the migration requires it
2. create and verify a PostgreSQL backup
3. run `python -m api_server.production_check`
4. run `alembic upgrade head` exactly once as the release migration job
5. deploy new application instances
6. wait for `GET /health`
7. require `GET /ready` to return HTTP 200
8. verify `GET /v1/audit/integrity`
9. verify `GET /v1/audit/anchors/verify`
10. verify `GET /v1/ops/status`
11. shift traffic gradually
12. create a fresh external audit anchor after the release

Do not run Alembic concurrently from every application replica.

## Rollback

Application rollback and database rollback are different operations.

For an application-only regression with a backward-compatible schema, redeploy the previous image while retaining the current database.

For database recovery, follow `RECOVERY_RUNBOOK.md`. A database snapshot restore can trigger external audit-anchor rollback detection and must not be hidden by deleting or rewriting external anchors.

## Secret rotation

Use overlapping key rings where supported.

For service JWTs:

1. add the new key
2. set the new active `kid`
3. deploy
4. allow old short-lived credentials to expire
5. remove the old key only when no longer required

For verification webhooks:

1. add the new provider key ID
2. switch the provider to the new key
3. confirm authenticated deliveries
4. retire the old key

Historical audit HMAC and anchor receipt verification keys must remain available while historical records/receipts require them.

## Production checklist

Before accepting traffic:

- [ ] `APP_ENV=production`
- [ ] PostgreSQL is used and row-locking requirement is enabled
- [ ] database backup has been created and restore tested
- [ ] Alembic is at head
- [ ] container runs as non-root
- [ ] root filesystem is read-only
- [ ] secrets are injected outside Git
- [ ] JWT-only service auth is enabled
- [ ] legacy admin token is disabled
- [ ] trusted verification is required
- [ ] webhook key IDs are required
- [ ] human review is required
- [ ] automatic publish is disabled
- [ ] audit HMAC key ring is configured
- [ ] external WORM anchor is healthy and fresh
- [ ] rollout anchor freshness enforcement is enabled
- [ ] distributed ingress/API-gateway rate limits are configured
- [ ] request body limits are appropriate for expected payloads
- [ ] structured logs and operational alerts are collected externally
- [ ] Prometheus scraping is configured with a `metrics_reader` credential
- [ ] distributed edge/API-gateway rate limiting is active
- [ ] `/ready` returns HTTP 200


## Billing and abuse-protection deployment settings

Recommended starting values:

```text
MAX_REQUEST_BODY_BYTES=1048576
BILLING_RATE_LIMIT_PER_MINUTE=120
CREDENTIAL_RATE_LIMIT_PER_MINUTE=30
ROLLOUT_RATE_LIMIT_PER_MINUTE=30
VERIFICATION_WEBHOOK_RATE_LIMIT_PER_MINUTE=300
```

These counters are process-local. Configure equivalent or stricter distributed limits at the reverse proxy, load balancer, WAF, or API gateway so limits remain effective across multiple application replicas.

Provision billing ingestion with the least-privilege `billing_writer` role rather than a general admin credential.


## Final release gate

Immediately before traffic cutover, execute:

```bash
python -m api_server.release_gate
```

This is stricter than the configuration-only preflight because it also checks the connected database migration revision.

In JWT-only steady-state production, do not leave `SERVICE_IDENTITIES_JSON`, `INTERNAL_API_TOKEN`, or `CUSTOM_API_TOKEN` configured. Bootstrap or migration credentials should be removed after short-lived JWT issuance is operational.

The release gate also enforces bounded request-body and sensitive mutation rate-limit settings so accidental effectively-unlimited values cannot pass production preflight.


## External metrics and edge protection

The application exposes Prometheus-compatible process metrics at:

```text
GET /v1/ops/metrics
```

The endpoint requires a service credential with the dedicated `metrics_reader` role. Issue a short-lived credential through the normal credential lifecycle and configure the monitoring collector to renew it through an authorized integration rather than adding a static general-purpose API token.

The metrics surface contains bounded route templates, counts, latency summaries, incident signals, and alert states. It does not include request bodies, bearer tokens, concrete resource IDs, creator references, or secret values.

Production release gating requires:

```text
METRICS_EXPORT_MODE=prometheus
EDGE_RATE_LIMIT_MODE=external
```

`EDGE_RATE_LIMIT_MODE=external` is an explicit deployment contract: the process-local rate limiter remains defense in depth, while the production ingress/API gateway must provide distributed rate limiting across replicas, connection controls, and DDoS protection.


## Kubernetes deployment baseline

A provider-neutral hardened Kustomize base is available under:

```text
deploy/kubernetes/
```

It includes:

- restricted Pod Security namespace
- ServiceAccount token automount disabled
- three-replica Deployment
- zero-unavailable rolling updates
- startup/liveness/readiness probes
- CPU/memory requests and limits
- read-only root filesystem
- non-root UID/GID 10001
- dropped Linux capabilities
- RuntimeDefault seccomp
- projected read-only Secret files
- ClusterIP Service
- PodDisruptionBudget
- HPA
- ingress/egress NetworkPolicy

The Alembic migration Job is deliberately separate from the Deployment render. Run it once per release before rolling out application Pods.

See `deploy/kubernetes/README.md` for the migration sequence, secret contract, namespace access label, immutable image pinning, and provider-specific egress tightening guidance.


## Supply-chain release evidence

Before promoting an image, require the CI `supply-chain` job to pass.

The job provides:

- Python dependency vulnerability audit
- complete Git-history secret scan
- production-image vulnerability scan
- CycloneDX SBOM and SHA-256 checksum artifact

Promote the exact image content that passed these checks. In the target registry, prefer immutable digest promotion plus registry/platform signing and admission verification rather than rebuilding the image separately after CI.


## Attested image promotion

For production releases, use the digest emitted by the release workflow rather than rebuilding or deploying a mutable tag.

The release artifact `release-image.txt` contains the authoritative image reference:

```text
ghcr.io/<owner>/creator-revenue-agent@sha256:<digest>
```

Use that same digest for both the Kubernetes migration Job and Deployment. Verify the GitHub build-provenance and SBOM attestations before traffic cutover. See `RELEASE_SECURITY.md`.
