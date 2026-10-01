from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.api.client import CustomAPIClient
from app.config import settings
from app.orchestrator import Orchestrator


class AgentRisk(str, Enum):
    READ_ONLY = "read_only"
    PROPOSAL_ONLY = "proposal_only"
    HUMAN_GATED = "human_gated"
    PRODUCTION_MUTATION = "production_mutation"


@dataclass(frozen=True)
class AgentDecision:
    action: str
    risk: AgentRisk
    auto_executable: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentSnapshot:
    job_id: str
    approval: dict[str, Any]
    publication: dict[str, Any] | None
    proposal: dict[str, Any] | None
    experiment: dict[str, Any] | None
    review: dict[str, Any] | None
    change_set: dict[str, Any] | None
    rollout: dict[str, Any] | None
    statistics: dict[str, Any] | None
    audit_events: int


def _latest_payload(
    audit: list[dict[str, Any]],
    event_type: str,
) -> dict[str, Any] | None:
    for event in reversed(audit):
        if event.get("event_type") != event_type:
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


class BoundedAgent:
    """
    State-aware orchestration that automates only reversible/read-only work
    and proposal creation.

    The agent never makes human review decisions, starts experiments,
    publishes content, applies production change sets, or rolls back
    production state.
    """

    def __init__(
        self,
        api: CustomAPIClient | None = None,
    ) -> None:
        self.api = api or CustomAPIClient()
        self.orchestrator = Orchestrator(self.api)

    def create(self, brief: dict[str, Any]) -> dict[str, Any]:
        created = self.orchestrator.create_job(brief)
        job_id = created.get("job_id")
        if not job_id or created.get("status") == "rejected":
            return {
                "created": created,
                "agent": None,
            }
        return {
            "created": created,
            "agent": self.advance(str(job_id)),
        }

    def inspect(self, job_id: str) -> AgentSnapshot:
        approval = self.api.get_approval(job_id)
        audit = self.api.get_audit(job_id)

        publication: dict[str, Any] | None = None
        proposal: dict[str, Any] | None = None
        experiment: dict[str, Any] | None = None
        review: dict[str, Any] | None = None
        change_set: dict[str, Any] | None = None
        rollout: dict[str, Any] | None = None
        statistics: dict[str, Any] | None = None

        publication_event = _latest_payload(
            audit,
            "publication_published",
        )
        if publication_event is not None:
            publication = self.api.get_publication(job_id)

        proposal_event = _latest_payload(
            audit,
            "optimizer_proposal_created",
        )
        if proposal_event is not None:
            proposal_id = proposal_event.get("proposal_id")
            if isinstance(proposal_id, str):
                proposal = self.api.get_optimization_proposal(
                    proposal_id
                )

        experiment_event = _latest_payload(
            audit,
            "experiment_created",
        )
        if experiment_event is not None:
            experiment_id = experiment_event.get("experiment_id")
            if isinstance(experiment_id, str):
                experiment = self.api.get_experiment(experiment_id)
                if experiment.get("status") in {
                    "running",
                    "completed",
                }:
                    statistics = (
                        self.api.get_experiment_statistics(
                            experiment_id
                        )
                    )

        review_event = _latest_payload(
            audit,
            "experiment_review_recorded",
        )
        if review_event is not None and experiment is not None:
            experiment_id = experiment.get("experiment_id")
            if isinstance(experiment_id, str):
                review = self.api.get_experiment_review(
                    experiment_id
                )

        change_set_event = _latest_payload(
            audit,
            "change_set_created",
        )
        if change_set_event is not None:
            change_set_id = change_set_event.get("change_set_id")
            if isinstance(change_set_id, str):
                change_set = self.api.get_change_set(change_set_id)

        rollout_event = _latest_payload(
            audit,
            "rollout_applied",
        )
        if rollout_event is not None:
            rollout_id = rollout_event.get("rollout_id")
            if isinstance(rollout_id, str):
                rollout = self.api.get_rollout(rollout_id)

        return AgentSnapshot(
            job_id=job_id,
            approval=approval,
            publication=publication,
            proposal=proposal,
            experiment=experiment,
            review=review,
            change_set=change_set,
            rollout=rollout,
            statistics=statistics,
            audit_events=len(audit),
        )

    def plan(
        self,
        snapshot: AgentSnapshot,
        *,
        window: str = "7d",
    ) -> AgentDecision:
        approval_status = snapshot.approval.get("status")
        if approval_status == "rejected":
            return AgentDecision(
                action="stop_rejected",
                risk=AgentRisk.READ_ONLY,
                auto_executable=False,
                reason="human approval rejected the job",
            )
        if approval_status != "approved":
            return AgentDecision(
                action="wait_for_human_approval",
                risk=AgentRisk.HUMAN_GATED,
                auto_executable=False,
                reason="publication requires explicit human approval",
            )

        if snapshot.publication is None:
            return AgentDecision(
                action="publish",
                risk=AgentRisk.PRODUCTION_MUTATION,
                auto_executable=False,
                reason=(
                    "publishing is an external side effect and is never "
                    "performed by the bounded agent"
                ),
            )

        if snapshot.proposal is None:
            return AgentDecision(
                action="create_optimization_proposal",
                risk=AgentRisk.PROPOSAL_ONLY,
                auto_executable=True,
                reason=(
                    "optimizer proposals do not mutate price, content, "
                    "publishing, or traffic"
                ),
                details={
                    "publication_id": snapshot.publication[
                        "publication_id"
                    ],
                    "window": window,
                },
            )

        proposal_status = snapshot.proposal.get("status")
        if proposal_status == "rejected":
            return AgentDecision(
                action="stop_optimizer_rejected",
                risk=AgentRisk.READ_ONLY,
                auto_executable=False,
                reason="human review rejected the optimizer proposal",
            )
        if proposal_status != "approved":
            return AgentDecision(
                action="wait_for_optimizer_review",
                risk=AgentRisk.HUMAN_GATED,
                auto_executable=False,
                reason=(
                    "the agent cannot approve its own optimization "
                    "proposal"
                ),
            )

        if snapshot.experiment is None:
            return AgentDecision(
                action="select_and_create_experiment",
                risk=AgentRisk.HUMAN_GATED,
                auto_executable=False,
                reason=(
                    "choosing a recommendation changes the experiment "
                    "plan and requires an operator"
                ),
                details={
                    "proposal_id": snapshot.proposal["proposal_id"],
                    "recommendations": snapshot.proposal.get(
                        "recommendations",
                        [],
                    ),
                },
            )

        experiment_status = snapshot.experiment.get("status")
        if experiment_status == "draft":
            return AgentDecision(
                action="start_experiment",
                risk=AgentRisk.PRODUCTION_MUTATION,
                auto_executable=False,
                reason=(
                    "starting an experiment can affect live traffic and "
                    "requires an operator"
                ),
            )
        if experiment_status == "cancelled":
            return AgentDecision(
                action="stop_experiment_cancelled",
                risk=AgentRisk.READ_ONLY,
                auto_executable=False,
                reason="the experiment was cancelled",
            )
        if experiment_status == "running":
            gates = (
                snapshot.statistics.get("gates", {})
                if snapshot.statistics
                else {}
            )
            if gates.get("all_passed") is True:
                return AgentDecision(
                    action="complete_experiment",
                    risk=AgentRisk.HUMAN_GATED,
                    auto_executable=False,
                    reason=(
                        "statistical readiness passed, but completion "
                        "remains an operator action"
                    ),
                    details={"gates": gates},
                )
            return AgentDecision(
                action="collect_experiment_data",
                risk=AgentRisk.READ_ONLY,
                auto_executable=False,
                reason="statistical readiness gates are not yet met",
                details={"gates": gates},
            )

        if experiment_status != "completed":
            return AgentDecision(
                action="stop_unknown_experiment_state",
                risk=AgentRisk.HUMAN_GATED,
                auto_executable=False,
                reason=(
                    "the experiment is in an unsupported state; "
                    "operator inspection is required"
                ),
            )

        if snapshot.review is None:
            return AgentDecision(
                action="wait_for_experiment_review",
                risk=AgentRisk.HUMAN_GATED,
                auto_executable=False,
                reason=(
                    "the bounded agent never selects an experiment "
                    "winner"
                ),
                details={
                    "statistics": snapshot.statistics or {},
                },
            )

        review_decision = snapshot.review.get("decision")
        if review_decision in {
            "control_preferred",
            "inconclusive",
        }:
            return AgentDecision(
                action="stop_no_rollout",
                risk=AgentRisk.READ_ONLY,
                auto_executable=False,
                reason=(
                    "human experiment review did not select the variant"
                ),
                details={"decision": review_decision},
            )
        if review_decision != "variant_preferred":
            return AgentDecision(
                action="stop_unknown_review_decision",
                risk=AgentRisk.HUMAN_GATED,
                auto_executable=False,
                reason="unsupported review decision",
            )

        if snapshot.change_set is None:
            return AgentDecision(
                action="create_change_set",
                risk=AgentRisk.PROPOSAL_ONLY,
                auto_executable=True,
                reason=(
                    "a change set is proposal-only and still requires a "
                    "separate release-manager approval before apply"
                ),
                details={
                    "review_id": snapshot.review["review_id"],
                },
            )

        change_status = snapshot.change_set.get("status")
        if change_status == "rejected":
            return AgentDecision(
                action="stop_change_set_rejected",
                risk=AgentRisk.READ_ONLY,
                auto_executable=False,
                reason="release manager rejected the change set",
            )
        if change_status == "pending_approval":
            return AgentDecision(
                action="wait_for_change_set_approval",
                risk=AgentRisk.HUMAN_GATED,
                auto_executable=False,
                reason=(
                    "a separate release manager must approve the "
                    "change set"
                ),
            )
        if change_status == "approved":
            return AgentDecision(
                action="apply_rollout",
                risk=AgentRisk.PRODUCTION_MUTATION,
                auto_executable=False,
                reason=(
                    "production mutation is outside bounded-agent "
                    "authority"
                ),
            )

        if snapshot.rollout is not None:
            if snapshot.rollout.get("status") == "rolled_back":
                return AgentDecision(
                    action="stop_rolled_back",
                    risk=AgentRisk.READ_ONLY,
                    auto_executable=False,
                    reason="rollout has already been rolled back",
                )
            return AgentDecision(
                action="monitor_rollout",
                risk=AgentRisk.READ_ONLY,
                auto_executable=True,
                reason=(
                    "rollout monitoring is read-only; drift is escalated "
                    "without automatic rollback"
                ),
                details={
                    "rollout_id": snapshot.rollout["rollout_id"],
                },
            )

        return AgentDecision(
            action="inspect_change_set",
            risk=AgentRisk.HUMAN_GATED,
            auto_executable=False,
            reason=(
                "change-set state is not actionable without operator "
                "inspection"
            ),
            details={"status": change_status},
        )

    def advance(
        self,
        job_id: str,
        *,
        window: str = "7d",
        max_steps: int | None = None,
    ) -> dict[str, Any]:
        budget = max_steps or settings.agent_max_auto_steps
        budget = max(1, min(int(budget), 20))
        trace: list[dict[str, Any]] = []

        for _ in range(budget):
            snapshot = self.inspect(job_id)
            decision = self.plan(snapshot, window=window)
            trace.append(
                {
                    "action": decision.action,
                    "risk": decision.risk.value,
                    "auto_executable": decision.auto_executable,
                    "reason": decision.reason,
                    "details": decision.details,
                }
            )

            if not decision.auto_executable:
                return {
                    "job_id": job_id,
                    "status": "paused",
                    "next_action": decision.action,
                    "trace": trace,
                }

            if decision.action == "create_optimization_proposal":
                self.api.create_optimization_proposal(
                    publication_id=decision.details[
                        "publication_id"
                    ],
                    window=decision.details["window"],
                )
                continue

            if decision.action == "create_change_set":
                self.api.create_change_set(
                    review_id=decision.details["review_id"],
                    created_by="bounded-agent",
                )
                continue

            if decision.action == "monitor_rollout":
                monitoring = self.api.monitor_rollout(
                    decision.details["rollout_id"]
                )
                trace.append(
                    {
                        "action": "rollout_observation",
                        "risk": AgentRisk.READ_ONLY.value,
                        "auto_executable": True,
                        "reason": "read-only rollout observation",
                        "details": monitoring,
                    }
                )
                if (
                    monitoring.get("monitoring_status")
                    == "state_drift"
                ):
                    trace.append(
                        {
                            "action": "escalate_state_drift",
                            "risk": (
                                AgentRisk.HUMAN_GATED.value
                            ),
                            "auto_executable": False,
                            "reason": (
                                "state drift requires human incident "
                                "review; automatic rollback is forbidden"
                            ),
                            "details": {
                                "rollout_id": decision.details[
                                    "rollout_id"
                                ]
                            },
                        }
                    )
                    return {
                        "job_id": job_id,
                        "status": "attention_required",
                        "next_action": "escalate_state_drift",
                        "trace": trace,
                    }
                return {
                    "job_id": job_id,
                    "status": "observed",
                    "next_action": "continue_monitoring",
                    "trace": trace,
                }

            return {
                "job_id": job_id,
                "status": "attention_required",
                "next_action": "unsupported_auto_action",
                "trace": trace,
            }

        return {
            "job_id": job_id,
            "status": "attention_required",
            "next_action": "step_budget_exhausted",
            "trace": trace,
        }
