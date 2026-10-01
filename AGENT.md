# Bounded Agent Supervisor

The agent is intentionally more capable than the original one-shot
orchestrator, but its authority is narrower than the API's full RBAC surface.

## Goal

The supervisor reconstructs workflow state from the compliance audit trail
and current API records, then selects the next safe action. It can resume a
job after a process restart without keeping a private in-memory state machine.

## Automatic actions

The bounded agent may automatically:

- inspect approvals, experiments, change sets, rollouts, and statistics
- create an optimizer proposal after a publication already exists
- create a pending change set after a human review recorded
  `variant_preferred`
- monitor an already-applied rollout
- surface state drift for incident handling

These actions are either read-only or proposal-only. They do not publish,
start traffic experiments, select an experiment winner, approve a change set,
apply a production change, or rollback production.

## Mandatory human/operator boundaries

The agent pauses for:

- initial human content approval
- publication
- optimizer review
- recommendation selection / experiment creation
- experiment start and completion
- experiment-result winner review
- change-set approval
- rollout apply
- rollback or any state-drift response

The API's existing RBAC and separation-of-duties rules remain authoritative.

## Resumability

`BoundedAgent.inspect(job_id)` uses audit events to discover the latest
publication, optimizer proposal, experiment, review, change set, and rollout
IDs, then fetches their current records. This makes the supervisor resilient
to worker restarts and avoids a second competing workflow state store.

## Step budget

`AGENT_MAX_AUTO_STEPS` bounds one call to `advance()`. The default is 4
and the implementation clamps the runtime budget to 1..20. Exceeding the
budget stops with `step_budget_exhausted`.

## Drift handling

Rollout monitoring is read-only. If the API returns
`monitoring_status=state_drift`, the agent returns
`attention_required / escalate_state_drift`. It never calls rollback
automatically.
