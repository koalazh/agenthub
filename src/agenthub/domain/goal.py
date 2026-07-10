from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GoalStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    RUNNING = "running"
    WAITING = "waiting"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class DeliveryMode(StrEnum):
    CANDIDATE_COMMIT = "candidate_commit"
    PATCH = "patch"


class IndependenceRequirement(StrEnum):
    VERIFIER_MUST_NOT_EQUAL_EXECUTOR = "verifier_must_not_equal_executor"


class DeliveryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: DeliveryMode = DeliveryMode.CANDIDATE_COMMIT
    auto_merge: bool = False

    @model_validator(mode="after")
    def reject_auto_merge(self) -> "DeliveryPolicy":
        if self.auto_merge:
            raise ValueError("MVP delivery policy cannot enable automatic merge")
        return self


class GoalContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    objective: str = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    constraints: tuple[str, ...] = ()
    prohibited_actions: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = Field(min_length=1)
    required_independence: tuple[IndependenceRequirement, ...] = (
        IndependenceRequirement.VERIFIER_MUST_NOT_EQUAL_EXECUTOR,
    )
    delivery: DeliveryPolicy = DeliveryPolicy()

    @field_validator(
        "acceptance_criteria",
        "constraints",
        "prohibited_actions",
        "required_evidence",
    )
    @classmethod
    def reject_blank_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in values):
            raise ValueError("contract lists cannot contain blank items")
        return values


class InvalidGoalTransition(ValueError):
    pass


_ALLOWED_TRANSITIONS: dict[GoalStatus, frozenset[GoalStatus]] = {
    GoalStatus.DRAFT: frozenset({GoalStatus.PLANNED, GoalStatus.CANCELED}),
    GoalStatus.PLANNED: frozenset({GoalStatus.RUNNING, GoalStatus.CANCELED}),
    GoalStatus.RUNNING: frozenset(
        {GoalStatus.WAITING, GoalStatus.REVIEW, GoalStatus.FAILED, GoalStatus.CANCELED}
    ),
    GoalStatus.WAITING: frozenset(
        {GoalStatus.RUNNING, GoalStatus.FAILED, GoalStatus.CANCELED}
    ),
    GoalStatus.REVIEW: frozenset(
        {GoalStatus.RUNNING, GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.CANCELED}
    ),
    GoalStatus.COMPLETED: frozenset(),
    GoalStatus.FAILED: frozenset(),
    GoalStatus.CANCELED: frozenset(),
}


class Goal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^goal_[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    status: GoalStatus = GoalStatus.DRAFT
    owner_user_id: str = Field(min_length=1)
    project_root: Path
    default_branch: str = Field(min_length=1)
    contract: GoalContract
    created_at: datetime
    updated_at: datetime

    @field_validator("project_root")
    @classmethod
    def require_absolute_project_root(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("project_root must be absolute")
        return value.resolve()

    @model_validator(mode="after")
    def validate_timestamps(self) -> "Goal":
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("goal timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self

    def transition_to(self, target: GoalStatus, *, actor: str) -> "Goal":
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise InvalidGoalTransition(f"cannot transition goal from {self.status} to {target}")
        if target is GoalStatus.COMPLETED and actor != "completion_controller":
            raise InvalidGoalTransition("only completion_controller can complete a goal")
        return self.model_copy(update={"status": target, "updated_at": datetime.now(UTC)})
