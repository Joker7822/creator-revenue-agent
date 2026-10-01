# Experiments

Experiments convert an approved optimizer recommendation into a controlled plan.

They do **not** automatically change price, content, publishing, or traffic routing.

## Lifecycle API

```text
POST /v1/experiments
GET  /v1/experiments/{experiment_id}
POST /v1/experiments/{experiment_id}/start
POST /v1/experiments/{experiment_id}/complete
POST /v1/experiments/{experiment_id}/cancel
```

## Assignment and measurement API

```text
POST /v1/experiments/{experiment_id}/assignments
POST /v1/experiments/{experiment_id}/events
POST /v1/experiments/{experiment_id}/transactions
GET  /v1/experiments/{experiment_id}/results
```

Assignments require a running experiment. The caller supplies an opaque subject key. The raw key is never persisted; the service stores only a SHA-256 hash scoped to the experiment.

Assignment is deterministic for the same experiment and subject key.

## Measurement sources

Experiment engagement events:

- impression
- click

Revenue events are not copied. Existing Billing API transactions are linked to an experiment assignment by transaction ID.

This keeps the billing ledger authoritative for:

- sale
- refund
- amount
- currency

## Results

Results are returned separately for `control` and `variant`:

- assignments
- impressions
- clicks
- purchases
- refunds
- CTR
- CVR
- currency-separated revenue

The API also returns descriptive deltas.

It does **not** automatically declare a winner. With fewer than 20 clicks in either arm, evaluation status is `insufficient_data`. Otherwise it becomes `ready_for_manual_review`.

## Privacy

Do not use email addresses, government identifiers, or other direct identifiers as subject keys in production. Use an internal opaque or pseudonymous identifier. Even though the raw key is not stored, the caller remains responsible for data minimization.

## Safety and control

Starting or measuring an experiment does not:

- change a product price
- replace content
- publish or republish content
- bypass policy or approval gates

Execution remains separate from measurement.
