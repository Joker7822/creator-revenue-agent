# creator-revenue-agent

AI-powered creator revenue orchestration built around proprietary APIs.

## Scope

This repository contains the orchestration layer, proprietary API server, persistence layer, CI/CD, API contracts, tests, and safety controls.

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
           +--> Audit API
           +--> Analytics API      (next)
    |
    +--> SQL database
```

## Current implementation

Implemented:

- content metadata and policy APIs
- human approval workflow
- gated/idempotent publishing
- products and proprietary transaction ingestion
- revenue aggregation by currency
- audit trail
- bearer-token service authentication
- SQLite development database / SQLAlchemy abstraction
- FastAPI / Docker / pytest / GitHub Actions CI

## Billing model

Money is stored as integer **minor units** plus a 3-letter currency code.

Examples:

```text
JPY 1500 -> ¥1,500
USD 1500 -> $15.00
```

The API never sums different currencies together. Revenue is returned in one bucket per currency.

## Billing endpoints

```text
POST /v1/products
GET  /v1/products/{product_id}
POST /v1/transactions
GET  /v1/revenue
```

A product can only be created for an existing published publication.

Transactions require a caller-supplied `transaction_id` and are idempotent. Reusing the same ID with different transaction data returns HTTP 409.

Supported transaction kinds:

- `sale`
- `refund`

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
Transaction
   |
Revenue by currency
   |
Analytics / optimization (next)
```

## Database tables

- `jobs`
- `approvals`
- `publications`
- `products`
- `transactions`
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
