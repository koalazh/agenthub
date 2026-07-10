from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HarnessMetadata(StrictModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    goal_id: str = Field(pattern=r"^goal_[A-Za-z0-9_-]+$")


class HarnessBounds(StrictModel):
    max_parallelism: int = Field(ge=1)
    max_agent_runs: int = Field(ge=1)
    max_patch_versions: int = Field(ge=1)
    max_loop_iterations: int = Field(ge=1)
    max_wall_time_seconds: int = Field(ge=1)
    max_cost_usd: float = Field(gt=0)


class AgentSelector(StrictModel):
    capabilities: tuple[str, ...] = ()
    agent_id: str | None = None
    prefer_binding_from: str | None = None
    exclude_agents_from: tuple[str, ...] = ()

    @model_validator(mode="after")
    def require_selection_criterion(self) -> "AgentSelector":
        if not (self.capabilities or self.agent_id or self.prefer_binding_from):
            raise ValueError("selector requires capabilities, agent_id, or prefer_binding_from")
        return self


class WorkspaceSpec(StrictModel):
    mode: Literal["read_only", "write_candidate"]


class RoleOverlay(StrictModel):
    role: str = Field(min_length=1, max_length=100)
    mission: str | None = Field(default=None, max_length=2000)
    instructions: tuple[str, ...] = ()


class BaseStep(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    depends_on: tuple[str, ...] = ()

    @field_validator("depends_on")
    @classmethod
    def dependencies_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("depends_on cannot contain duplicates")
        return values


class AgentCallStep(BaseStep):
    kind: Literal["agent_call"]
    task: str = Field(min_length=1, max_length=10_000)
    selector: AgentSelector
    workspace: WorkspaceSpec
    role_overlay: RoleOverlay | None = None
    outputs: tuple[str, ...] = Field(min_length=1)


class ParallelBranch(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_-]*$")
    agent_call: AgentCallStep


class ParallelStep(BaseStep):
    kind: Literal["parallel"]
    branches: tuple[ParallelBranch, ...] = Field(min_length=2)


class GateCheck(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    command: str = Field(min_length=1, max_length=2000)
    timeout_seconds: int = Field(default=600, ge=1, le=3600)

    @field_validator("command")
    @classmethod
    def reject_multiline_commands(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("gate command must be a single command line")
        return value


class RuntimeGateStep(BaseStep):
    kind: Literal["runtime_gate"]
    checks: tuple[GateCheck, ...] = Field(min_length=1)


class ReviewStep(BaseStep):
    kind: Literal["review"]
    selector: AgentSelector
    inputs: tuple[str, ...] = Field(min_length=1)
    outputs: tuple[str, ...] = Field(min_length=1)


class LoopAgentCall(StrictModel):
    task: str = Field(min_length=1, max_length=10_000)
    selector: AgentSelector
    role_overlay: RoleOverlay | None = None


class InheritedStep(StrictModel):
    inherit_from: str = Field(min_length=1, max_length=100)


class LoopBody(StrictModel):
    agent_call: LoopAgentCall
    runtime_gate: InheritedStep
    review: InheritedStep


class LoopStep(BaseStep):
    kind: Literal["loop"]
    max_iterations: int = Field(ge=1)
    continue_when: Literal["review_requires_changes"]
    body: LoopBody


class WaitApprovalStep(BaseStep):
    kind: Literal["wait_approval"]
    approval_type: Literal["capability", "budget", "harness_launch", "human_input"]
    prompt: str = Field(min_length=1, max_length=2000)


class FinalizeStep(BaseStep):
    kind: Literal["finalize"]
    delivery: Literal["candidate_commit", "patch"]


HarnessStep = Annotated[
    AgentCallStep
    | ParallelStep
    | RuntimeGateStep
    | ReviewStep
    | LoopStep
    | WaitApprovalStep
    | FinalizeStep,
    Field(discriminator="kind"),
]


class ProgressiveHarness(StrictModel):
    api_version: Literal["agenthub.io/harness/v1"]
    kind: Literal["ProgressiveHarness"]
    metadata: HarnessMetadata
    bounds: HarnessBounds
    mandatory_gates: frozenset[Literal["tests", "independent_review"]]
    steps: tuple[HarnessStep, ...] = Field(min_length=1)

    @field_validator("mandatory_gates")
    @classmethod
    def require_mvp_gates(
        cls, values: frozenset[Literal["tests", "independent_review"]]
    ) -> frozenset[Literal["tests", "independent_review"]]:
        required = {"tests", "independent_review"}
        if not required.issubset(values):
            raise ValueError("tests and independent_review are mandatory MVP gates")
        return values

    @model_validator(mode="after")
    def require_unique_step_ids(self) -> "ProgressiveHarness":
        ids = [step.id for step in self.steps]
        if len(set(ids)) != len(ids):
            raise ValueError("step ids must be unique")
        return self
