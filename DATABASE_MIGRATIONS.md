# Database migrations

Database schema changes are managed with Alembic.

## Upgrade

```bash
alembic upgrade head
```

Always run the migration as a deployment/release step before starting a new application version.

## Current revision

```bash
alembic current
```

## Create a new revision

After changing SQLAlchemy models:

```bash
alembic revision --autogenerate -m "describe change"
```

Review generated migrations before committing them, especially for SQLite batch operations, destructive changes, defaults, and data backfills.

## Legacy database adoption

Revision `20261001_0001` is intentionally compatible with databases previously created through `Base.metadata.create_all()`.

For each baseline table it:

- keeps an existing table intact
- creates a missing table
- creates missing regular indexes
- records the Alembic revision after a successful upgrade

This lets an existing SQLite development database enter the migration chain without dropping its data.

## Deployment rule

Application import no longer creates tables. A new or upgraded environment must run:

```bash
alembic upgrade head
```

before serving traffic.

For production, back up the database before migrations and run migrations once as a release job rather than concurrently in every application replica.


## Trusted verification revision

Revision `20261001_0002` adds:

- `verification_records`
- `jobs.creator_ref`
- `jobs.age_verification_id`
- `jobs.consent_verification_id`
- `jobs.real_person_consent_verification_id`

The new job columns are nullable so legacy rows remain readable. Production policy should enable `REQUIRE_TRUSTED_VERIFICATION=true` for newly created jobs.


## Verification webhook ledger revision

Revision `20261001_0003` adds `verification_webhook_events`, including a unique provider/event-ID constraint, body SHA-256, linked verification record, persisted response snapshot, and receive timestamp.


## Webhook key rotation revision

Revision `20261001_0004` adds `verification_webhook_events.key_id` and its index. Existing event rows are backfilled to `legacy` before the column becomes non-nullable.
