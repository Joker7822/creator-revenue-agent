from __future__ import annotations

from typing import Any

from app.agent import BoundedAgent


class FakeAPI:
    def __init__(self) -> None:
        self.approval = {
            "job_id": "job_1",
            "status": "pending_review",
        }
        self.audit: list[dict[str, Any]] = []
        self.publication: dict[str, Any] | None = None
        self.proposal: dict[str, Any] | None = None
        self.experiment: dict[str, Any] | None = None
        self.review: dict[str, Any] | None = None
        self.change_set: dict[str, Any] | None = None
        self.rollout: dict[str, Any] | None = None
        self.statistics: dict[str, Any] | None = None
        self.monitoring_status = "state_consistent"
        self.created_proposals = 0
        self.created_change_sets = 0
        self.rollback_calls = 0

    def get_approval(self, job_id: str) -> dict[str, Any]:
        return self.approval

    def get_audit(self, job_id: str) -> list[dict[str, Any]]:
        return list(self.audit)

    def get_publication(self, job_id: str) -> dict[str, Any]:
        assert self.publication is not None
        return self.publication

    def get_optimization_proposal(
        self,
        proposal_id: str,
    ) -> dict[str, Any]:
        assert self.proposal is not None
        return self.proposal

    def get_experiment(
        self,
        experiment_id: str,
    ) -> dict[str, Any]:
        assert self.experiment is not None
        return self.experiment

    def get_experiment_statistics(
        self,
        experiment_id: str,
    ) -> dict[str, Any]:
        assert self.statistics is not None
        return self.statistics

    def get_experiment_review(
        self,
        experiment_id: str,
    ) -> dict[str, Any]:
        assert self.review is not None
        return self.review

    def get_change_set(
        self,
        change_set_id: str,
    ) -> dict[str, Any]:
        assert self.change_set is not None
        return self.change_set

    def get_rollout(self, rollout_id: str) -> dict[str, Any]:
        assert self.rollout is not None
        return self.rollout

    def create_optimization_proposal(
        self,
        *,
        publication_id: str,
        window: str,
    ) -> dict[str, Any]:
        self.created_proposals += 1
        self.proposal = {
            "proposal_id": "opt_1",
            "publication_id": publication_id,
            "status": "pending_review",
            "recommendations": [],
        }
        self.audit.append(
            {
                "event_type": "optimizer_proposal_created",
                "payload": {
                    "proposal_id": "opt_1",
                    "publication_id": publication_id,
                },
            }
        )
        return self.proposal

    def create_change_set(
        self,
        *,
        review_id: str,
        created_by: str,
    ) -> dict[str, Any]:
        self.created_change_sets += 1
        self.change_set = {
            "change_set_id": "chg_1",
            "review_id": review_id,
            "status": "pending_approval",
        }
        self.audit.append(
            {
                "event_type": "change_set_created",
                "payload": {
                    "change_set_id": "chg_1",
                    "review_id": review_id,
                },
            }
        )
        return self.change_set

    def monitor_rollout(
        self,
        rollout_id: str,
    ) -> dict[str, Any]:
        return {
            "rollout_id": rollout_id,
            "monitoring_status": self.monitoring_status,
            "automatic_rollback": False,
        }

    def rollback_rollout(
        self,
        rollout_id: str,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        self.rollback_calls += 1
        raise AssertionError("bounded agent must never rollback")


def _published(api: FakeAPI) -> None:
    api.approval["status"] = "approved"
    api.publication = {
        "publication_id": "pub_1",
        "job_id": "job_1",
        "status": "published",
    }
    api.audit.append(
        {
            "event_type": "publication_published",
            "payload": {"publication_id": "pub_1"},
        }
    )


def _approved_proposal(api: FakeAPI) -> None:
    _published(api)
    api.proposal = {
        "proposal_id": "opt_1",
        "publication_id": "pub_1",
        "status": "approved",
        "recommendations": [
            {
                "type": "price_test",
                "action": "test_lower_price",
            }
        ],
    }
    api.audit.append(
        {
            "event_type": "optimizer_proposal_created",
            "payload": {"proposal_id": "opt_1"},
        }
    )


def _completed_experiment_with_review(
    api: FakeAPI,
) -> None:
    _approved_proposal(api)
    api.experiment = {
        "experiment_id": "exp_1",
        "proposal_id": "opt_1",
        "status": "completed",
    }
    api.statistics = {
        "gates": {"all_passed": True},
        "decision": "manual_review_required",
        "winner": None,
    }
    api.review = {
        "review_id": "rev_1",
        "experiment_id": "exp_1",
        "decision": "variant_preferred",
    }
    api.audit.extend(
        [
            {
                "event_type": "experiment_created",
                "payload": {"experiment_id": "exp_1"},
            },
            {
                "event_type": "experiment_review_recorded",
                "payload": {
                    "experiment_id": "exp_1",
                    "review_id": "rev_1",
                    "decision": "variant_preferred",
                },
            },
        ]
    )


def test_pending_human_review_stops_agent() -> None:
    api = FakeAPI()
    agent = BoundedAgent(api)  # type: ignore[arg-type]

    result = agent.advance("job_1")

    assert result["status"] == "paused"
    assert result["next_action"] == "wait_for_human_approval"
    assert api.created_proposals == 0


def test_published_job_auto_creates_proposal_only() -> None:
    api = FakeAPI()
    _published(api)
    agent = BoundedAgent(api)  # type: ignore[arg-type]

    result = agent.advance("job_1")

    assert api.created_proposals == 1
    assert result["status"] == "paused"
    assert result["next_action"] == "wait_for_optimizer_review"
    assert [step["action"] for step in result["trace"]] == [
        "create_optimization_proposal",
        "wait_for_optimizer_review",
    ]


def test_approved_proposal_does_not_choose_experiment() -> None:
    api = FakeAPI()
    _approved_proposal(api)
    agent = BoundedAgent(api)  # type: ignore[arg-type]

    result = agent.advance("job_1")

    assert result["next_action"] == "select_and_create_experiment"
    assert result["trace"][-1]["auto_executable"] is False


def test_variant_review_auto_creates_change_set_only() -> None:
    api = FakeAPI()
    _completed_experiment_with_review(api)
    agent = BoundedAgent(api)  # type: ignore[arg-type]

    result = agent.advance("job_1")

    assert api.created_change_sets == 1
    assert result["next_action"] == "wait_for_change_set_approval"


def test_approved_change_set_never_auto_applies() -> None:
    api = FakeAPI()
    _completed_experiment_with_review(api)
    api.change_set = {
        "change_set_id": "chg_1",
        "status": "approved",
    }
    api.audit.append(
        {
            "event_type": "change_set_created",
            "payload": {"change_set_id": "chg_1"},
        }
    )
    agent = BoundedAgent(api)  # type: ignore[arg-type]

    result = agent.advance("job_1")

    assert result["next_action"] == "apply_rollout"
    assert result["trace"][-1]["risk"] == "production_mutation"
    assert result["trace"][-1]["auto_executable"] is False


def test_rollout_drift_escalates_without_rollback() -> None:
    api = FakeAPI()
    _completed_experiment_with_review(api)
    api.change_set = {
        "change_set_id": "chg_1",
        "status": "applied",
    }
    api.rollout = {
        "rollout_id": "roll_1",
        "change_set_id": "chg_1",
        "status": "applied",
    }
    api.monitoring_status = "state_drift"
    api.audit.extend(
        [
            {
                "event_type": "change_set_created",
                "payload": {"change_set_id": "chg_1"},
            },
            {
                "event_type": "rollout_applied",
                "payload": {"rollout_id": "roll_1"},
            },
        ]
    )
    agent = BoundedAgent(api)  # type: ignore[arg-type]

    result = agent.advance("job_1")

    assert result["status"] == "attention_required"
    assert result["next_action"] == "escalate_state_drift"
    assert api.rollback_calls == 0
