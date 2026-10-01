# Optimizer

The optimizer is a proposal engine, not an autonomous revenue controller.

## API

```text
POST /v1/optimizer/proposals
GET  /v1/optimizer/proposals/{proposal_id}
POST /v1/optimizer/proposals/{proposal_id}/approve
POST /v1/optimizer/proposals/{proposal_id}/reject
```

## Inputs

The proposal engine snapshots:

- impressions
- clicks
- purchases
- refunds
- CTR
- CVR
- currency-separated revenue
- current active product price

## Current deterministic rules

The MVP uses bounded, inspectable heuristics:

- fewer than 100 impressions -> collect more impressions
- CTR below 5% after 100+ impressions -> test alternative non-explicit teaser metadata
- fewer than 20 clicks -> collect more click data
- CVR below 3% after 20+ clicks -> propose a price test up to 10% lower
- CVR above 10% with 5+ purchases -> propose a price test up to 10% higher
- refund rate above 20% with 5+ purchases -> review offer/expectation alignment
- posting-time optimization is represented only as a controlled experiment proposal until time-of-day evidence exists

## Human control

Every proposal starts as:

```text
pending_review
```

A human reviewer may approve or reject it.

Approval means **the experiment plan is approved**. There is intentionally no endpoint that automatically changes product price, republishes content, or bypasses policy/approval controls.

## Audit

Proposal creation and decisions create audit events:

- `optimizer_proposal_created`
- `optimizer_proposal_approved`
- `optimizer_proposal_rejected`
