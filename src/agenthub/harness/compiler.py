from pydantic import BaseModel, ConfigDict

from agenthub.harness.schema import AgentCallStep, ProgressiveHarness


class PhysicalStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    depends_on: tuple[str, ...]
    workspace_mode: str | None


class PhysicalPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    goal_id: str
    steps: tuple[PhysicalStep, ...]
    max_parallelism: int
    delivery: str


def compile_harness(harness: ProgressiveHarness) -> PhysicalPlan:
    by_id = {step.id: step for step in harness.steps}
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
            workspace_mode = step.workspace.mode if isinstance(step, AgentCallStep) else None
            ordered.append(
                PhysicalStep(
                    id=step.id,
                    kind=step.kind,
                    depends_on=step.depends_on,
                    workspace_mode=workspace_mode,
                )
            )
            emitted.add(step_id)
            pending.remove(step_id)

    finalizer = next(step for step in harness.steps if step.kind == "finalize")
    return PhysicalPlan(
        goal_id=harness.metadata.goal_id,
        steps=tuple(ordered),
        max_parallelism=harness.bounds.max_parallelism,
        delivery=finalizer.delivery,
    )
