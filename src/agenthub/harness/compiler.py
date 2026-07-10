from pydantic import BaseModel, ConfigDict

from agenthub.harness.schema import (
    AgentCallStep,
    LoopStep,
    ProgressiveHarness,
    ReviewStep,
    RuntimeGateStep,
    WorkspaceSpec,
)


class PhysicalStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    depends_on: tuple[str, ...]
    workspace_mode: str | None
    logical_step_id: str
    loop_id: str | None = None
    loop_iteration: int | None = None
    loop_phase: str | None = None


class PhysicalPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    goal_id: str
    steps: tuple[PhysicalStep, ...]
    max_parallelism: int
    delivery: str


def compile_harness(harness: ProgressiveHarness) -> PhysicalPlan:
    physical_steps: list[PhysicalStep] = []
    for step in harness.steps:
        if not isinstance(step, LoopStep):
            physical_steps.append(
                PhysicalStep(
                    id=step.id,
                    kind=step.kind,
                    depends_on=step.depends_on,
                    workspace_mode=(
                        step.workspace.mode if isinstance(step, AgentCallStep) else None
                    ),
                    logical_step_id=step.id,
                )
            )
            continue

        parents = step.depends_on
        for iteration in range(1, step.max_iterations + 1):
            repair_id = f"{step.id}_repair_{iteration}"
            gate_id = f"{step.id}_gate_{iteration}"
            review_id = f"{step.id}_review_{iteration}"
            physical_steps.extend(
                (
                    PhysicalStep(
                        id=repair_id,
                        kind="agent_call",
                        depends_on=parents,
                        workspace_mode="write_candidate",
                        logical_step_id=step.id,
                        loop_id=step.id,
                        loop_iteration=iteration,
                        loop_phase="repair",
                    ),
                    PhysicalStep(
                        id=gate_id,
                        kind="runtime_gate",
                        depends_on=(repair_id,),
                        workspace_mode=None,
                        logical_step_id=step.id,
                        loop_id=step.id,
                        loop_iteration=iteration,
                        loop_phase="gate",
                    ),
                    PhysicalStep(
                        id=review_id,
                        kind="review",
                        depends_on=(gate_id,),
                        workspace_mode=None,
                        logical_step_id=step.id,
                        loop_id=step.id,
                        loop_iteration=iteration,
                        loop_phase="review",
                    ),
                )
            )
            parents = (review_id,)
        physical_steps.append(
            PhysicalStep(
                id=step.id,
                kind="loop",
                depends_on=parents,
                workspace_mode=None,
                logical_step_id=step.id,
                loop_id=step.id,
                loop_phase="complete",
            )
        )

    by_id = {step.id: step for step in physical_steps}
    pending = set(by_id)
    ordered: list[PhysicalStep] = []
    emitted: set[str] = set()

    while pending:
        ready = sorted(
            step_id
            for step_id in pending
            if set(by_id[step_id].depends_on).issubset(emitted)
        )
        if not ready:
            raise ValueError("validated harness contains an unresolvable dependency graph")
        for step_id in ready:
            step = by_id[step_id]
            ordered.append(step)
            emitted.add(step_id)
            pending.remove(step_id)

    finalizer = next(step for step in harness.steps if step.kind == "finalize")
    return PhysicalPlan(
        goal_id=harness.metadata.goal_id,
        steps=tuple(ordered),
        max_parallelism=harness.bounds.max_parallelism,
        delivery=finalizer.delivery,
    )


def resolve_physical_step(
    harness: ProgressiveHarness, physical: PhysicalStep
) -> object:
    logical = next(step for step in harness.steps if step.id == physical.logical_step_id)
    if not isinstance(logical, LoopStep):
        return logical
    if physical.loop_phase == "repair":
        return AgentCallStep(
            id=physical.id,
            kind="agent_call",
            depends_on=physical.depends_on,
            task=logical.body.agent_call.task,
            selector=logical.body.agent_call.selector,
            workspace=WorkspaceSpec(mode="write_candidate"),
            role_overlay=logical.body.agent_call.role_overlay,
            outputs=("candidate_commit", "implementation_report"),
        )
    by_id = {step.id: step for step in harness.steps}
    if physical.loop_phase == "gate":
        inherited = by_id[logical.body.runtime_gate.inherit_from]
        assert isinstance(inherited, RuntimeGateStep)
        return inherited.model_copy(
            update={"id": physical.id, "depends_on": physical.depends_on}
        )
    if physical.loop_phase == "review":
        inherited = by_id[logical.body.review.inherit_from]
        assert isinstance(inherited, ReviewStep)
        return inherited.model_copy(
            update={"id": physical.id, "depends_on": physical.depends_on}
        )
    return logical
