# creator-revenue-agent

AI-powered creator revenue orchestration built around proprietary APIs.

## Scope

This repository contains the orchestration layer, CI/CD, API contracts, tests, and safety controls. Business APIs are proprietary and are called through a single internal client.

GitHub is used for source code and automation only. Do not commit generated adult media, identity documents, consent evidence, payment data, or secrets.

## Architecture

```text
GitHub Actions
    |
    v
Creator Revenue Agent
    |
    +--> Content API
    +--> Policy API
    +--> Approval API
    +--> Publishing API
    +--> Billing API
    +--> Analytics API
```

## Core flow

```text
Generate -> Policy check -> Human approval -> Publish -> Revenue -> Analytics
   ^                                                               |
   +------------------------ optimization loop ----------------------+
```

## Safety baseline

- Adults only; reject minors and age-ambiguous cases.
- Require documented consent.
- Real-person sexual depictions require explicit verified consent.
- Human review is enabled by default.
- Explicit assets must live outside GitHub.
- Secrets and verification documents must never be committed.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/run_agent.py --mode plan
```

## Repository

`Joker7822/creator-revenue-agent`
