from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agenthub.domain.goal import (
    DeliveryPolicy,
    Goal,
    GoalContract,
    GoalStatus,
    InvalidGoalTransition,
)


def make_goal(tmp_path: Path, status: GoalStatus = GoalStatus.DRAFT) -> Goal:
    now = datetime.now(UTC)
    return Goal(
        id="goal_test",
        title="Fix refresh race",
        status=status,
        owner_user_id="local-user",
        project_root=tmp_path,
        default_branch="main",
        contract=GoalContract(
            objective="Fix the concurrent refresh race",
            acceptance_criteria=("Regression test passes",),
            required_evidence=("Test output",),
        ),
        created_at=now,
        updated_at=now,
    )


def test_goal_contract_is_immutable(tmp_path: Path) -> None:
    goal = make_goal(tmp_path)

    with pytest.raises(ValidationError):
        goal.contract.objective = "A weaker objective"


def test_mvp_rejects_automatic_merge() -> None:
    with pytest.raises(ValidationError, match="automatic merge"):
        DeliveryPolicy(auto_merge=True)


def test_legal_goal_lifecycle_reaches_review(tmp_path: Path) -> None:
    goal = make_goal(tmp_path)

    goal = goal.transition_to(GoalStatus.PLANNED, actor="runtime")
    goal = goal.transition_to(GoalStatus.RUNNING, actor="runtime")
    goal = goal.transition_to(GoalStatus.REVIEW, actor="runtime")

    assert goal.status is GoalStatus.REVIEW


def test_illegal_goal_transition_is_rejected(tmp_path: Path) -> None:
    goal = make_goal(tmp_path)

    with pytest.raises(InvalidGoalTransition, match="draft.*completed"):
        goal.transition_to(GoalStatus.COMPLETED, actor="completion_controller")


def test_only_completion_controller_can_complete(tmp_path: Path) -> None:
    goal = make_goal(tmp_path, status=GoalStatus.REVIEW)

    with pytest.raises(InvalidGoalTransition, match="only completion_controller"):
        goal.transition_to(GoalStatus.COMPLETED, actor="worker")

    completed = goal.transition_to(GoalStatus.COMPLETED, actor="completion_controller")
    assert completed.status is GoalStatus.COMPLETED


def test_terminal_goal_cannot_transition(tmp_path: Path) -> None:
    goal = make_goal(tmp_path, status=GoalStatus.CANCELED)

    with pytest.raises(InvalidGoalTransition):
        goal.transition_to(GoalStatus.RUNNING, actor="runtime")
