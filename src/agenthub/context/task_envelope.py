from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskIdentity(FrozenModel):
    goal_id: str
    task_id: str
    run_id: str
    role: str


class TaskObjective(FrozenModel):
    statement: str = Field(min_length=1)


class GoalContext(FrozenModel):
    summary: str = Field(min_length=1)
    relevance: str = Field(min_length=1)


class TaskInputs(FrozenModel):
    handoffs: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()


class Permissions(FrozenModel):
    repository: Literal["read_only", "write_candidate"]
    network: Literal["deny", "allow", "allowlist"] = "deny"
    network_allowlist: tuple[str, ...] = ()


class TaskConstraints(FrozenModel):
    permissions: Permissions
    token_budget: int | None = Field(default=None, ge=1)
    deadline: datetime | None = None
    prohibited_actions: tuple[str, ...] = ()


class OutputContract(FrozenModel):
    kind: str
    schema_: dict[str, Any] = Field(default={}, alias="schema", serialization_alias="schema")
    artifact_dir: str
    artifacts: tuple[str, ...] = Field(min_length=1)


class EscalationPolicy(FrozenModel):
    allowed_proposals: tuple[
        Literal["request_context", "request_capability", "spawn_task", "report_blocker"],
        ...,
    ]


class TaskEnvelope(FrozenModel):
    api_version: Literal["agenthub.io/task-envelope/v1"] = "agenthub.io/task-envelope/v1"
    identity: TaskIdentity
    objective: TaskObjective
    goal_context: GoalContext
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    inputs: TaskInputs = TaskInputs()
    constraints: TaskConstraints
    output_contract: OutputContract
    escalation: EscalationPolicy
