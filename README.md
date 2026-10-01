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

For production, use a managed SQL database and schema migrations before deployment.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
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
