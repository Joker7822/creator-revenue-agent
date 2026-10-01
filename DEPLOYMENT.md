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
