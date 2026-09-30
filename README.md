# creator-revenue-agent

AI-powered creator revenue orchestration built around proprietary APIs.

## Scope

This repository contains the orchestration layer, proprietary API server, CI/CD, API contracts, tests, and safety controls.

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
           +--> Approval API       (next)
           +--> Publishing API     (next)
           +--> Billing API        (next)
           +--> Analytics API      (next)
```

## Current implementation

Implemented:

- `GET /health`
- `POST /v1/content/generate`
- `POST /v1/policy/evaluate`
- bearer-token service authentication
- deterministic local policy checks
- FastAPI server
- Docker image
- pytest coverage for API authentication and policy behavior

The current content endpoint generates **non-explicit campaign metadata only**. Explicit asset generation is intentionally not implemented before policy and approval controls are complete.

## Core flow

```text
Verification -> Metadata -> Policy -> Human approval -> Asset generation -> Publish
                                                        |
                                                        v
                                                Revenue / Analytics
```

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn api_server.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Run tests:

```bash
pytest -q
```

## Docker

```bash
docker build -t creator-revenue-agent .
docker run --rm -p 8000:8000 \
  -e INTERNAL_API_TOKEN=replace-me \
  -e MIN_CREATOR_AGE=18 \
  creator-revenue-agent
```

## Authentication

Protected endpoints require:

```http
Authorization: Bearer <INTERNAL_API_TOKEN>
```

`CUSTOM_API_TOKEN` is used by the orchestrator client. In a local single-service setup, it may be the same secret as `INTERNAL_API_TOKEN`.

## Safety baseline

- Adults only; reject minors and age-ambiguous cases.
- Require positive age verification.
- Require documented consent.
- Real-person sexual depictions require separately verified consent.
- Human review is enabled by default.
- Explicit assets must live outside GitHub.
- Secrets and verification documents must never be committed.

## GitHub Actions secrets

- `CUSTOM_API_BASE_URL`
- `CUSTOM_API_TOKEN`

## Repository

`Joker7822/creator-revenue-agent`
