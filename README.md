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
           +--> Audit API
           +--> Billing API        (next)
           +--> Analytics API      (next)
    |
    +--> SQL database
```

## Current implementation

Implemented:

- `GET /health`
- `POST /v1/content/generate`
- `POST /v1/policy/evaluate`
- `POST /v1/approvals`
- `GET /v1/approvals/{job_id}`
- `POST /v1/approvals/{job_id}/approve`
- `POST /v1/approvals/{job_id}/reject`
- `POST /v1/publish`
- `GET /v1/publications/{job_id}`
- `GET /v1/audit/{job_id}`
- bearer-token service authentication
- persistent job, policy, approval, publication and audit state
- SQLite development database
- SQLAlchemy persistence abstraction
- FastAPI server
- Docker image
- pytest / GitHub Actions CI

The current content endpoint generates **non-explicit campaign metadata only**. The publishing endpoint records an approved internal publication state; external asset delivery adapters are not implemented yet.

## Publishing gate

A job can be published only when both conditions are true:

```text
policy_allowed == true
AND
approval.status == approved
```

Publishing is idempotent by `job_id`; repeated requests return the existing publication instead of creating duplicates.

## Core flow

```text
Metadata
   |
   v
Policy
   |
   v
Approval
   |
   +---- rejected -> stop
   |
 approved
   |
   v
Publication record
   |
   v
Audit trail
   |
   v
Billing / analytics (next)
```

## Database

Default development database:

```text
sqlite:///./agent.db
```

Database tables:

- `jobs`
- `approvals`
- `publications`
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

## Authentication

Protected endpoints require:

```http
Authorization: Bearer <INTERNAL_API_TOKEN>
```

## Safety baseline

- Adults only; reject minors and age-ambiguous cases.
- Require positive age verification.
- Require documented consent.
- Real-person sexual depictions require separately verified consent.
- Approval cannot be created until policy evaluation has passed.
- Publishing cannot occur until approval is explicitly approved.
- Human review is enabled by default.
- Explicit assets must live outside GitHub.
- Secrets and verification documents must never be committed.

## Repository

`Joker7822/creator-revenue-agent`
