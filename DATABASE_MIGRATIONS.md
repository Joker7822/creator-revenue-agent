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
