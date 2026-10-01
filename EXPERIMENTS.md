# Experiments

Experiments convert an approved optimizer recommendation into a controlled plan.

They do **not** automatically change price, content, publishing, or traffic routing.

## API

```text
POST /v1/experiments
GET  /v1/experiments/{experiment_id}
POST /v1/experiments/{experiment_id}/start
POST /v1/experiments/{experiment_id}/complete
POST /v1/experiments/{experiment_id}/cancel
```

## State machine

```text
approved optimizer proposal
        |
        v
      draft
        |
        v
     running
      /   \
     v     v
completed cancelled
```

## Supported experimentable recommendations

- price tests
- non-explicit teaser tests
- posting-time tests

Data-collection and offer-review recommendations are intentionally not converted into A/B experiments.

## Safety and control

Starting an experiment only updates the experiment state. It does not:

- change a product price
- replace content
- publish or republish content
- route real traffic
- bypass policy or approval gates

Those execution adapters remain separate and require explicit implementation and authorization.

## Audit events

- `experiment_created`
- `experiment_started`
- `experiment_completed`
- `experiment_cancelled`
