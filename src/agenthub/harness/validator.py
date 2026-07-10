from dataclasses import dataclass

from pydantic import ValidationError

from agenthub.harness.schema import (
    AgentCallStep,
    LoopStep,
    ParallelStep,
    ProgressiveHarness,
    ReviewStep,
    RuntimeGateStep,
)


@dataclass(frozen=True)
class HarnessPolicy:
    max_parallelism: int = 3
    max_agent_runs: int = 20
    max_patch_versions: int = 5
    max_loop_iterations: int = 2
    max_wall_time_seconds: int = 7200
    max_cost_usd: float = 100.0


class HarnessValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def parse_harness(payload: dict[str, object]) -> ProgressiveHarness:
    try:
        return ProgressiveHarness.model_validate(payload)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ]
        raise HarnessValidationError(errors) from exc


def validate_harness(
    harness: ProgressiveHarness,
    *,
    goal_id: str,
    policy: HarnessPolicy | None = None,
) -> None:
    active_policy = policy or HarnessPolicy()
    errors: list[str] = []

    if harness.metadata.goal_id != goal_id:
        errors.append("harness metadata goal_id does not match the target goal")

    _validate_bounds(harness, active_policy, errors)
    _validate_graph(harness, errors)
    _validate_required_steps(harness, errors)
    _validate_independence(harness, errors)
    _validate_loop_references(harness, errors)
    _validate_agent_run_bound(harness, errors)

    if errors:
        raise HarnessValidationError(errors)


def _validate_bounds(
    harness: ProgressiveHarness, policy: HarnessPolicy, errors: list[str]
) -> None:
    requested = harness.bounds
    limits = {
        "max_parallelism": policy.max_parallelism,
        "max_agent_runs": policy.max_agent_runs,
        "max_patch_versions": policy.max_patch_versions,
        "max_loop_iterations": policy.max_loop_iterations,
        "max_wall_time_seconds": policy.max_wall_time_seconds,
        "max_cost_usd": policy.max_cost_usd,
    }
    for field, limit in limits.items():
        if getattr(requested, field) > limit:
            errors.append(f"bounds.{field} exceeds runtime policy limit {limit}")

    for step in harness.steps:
        if isinstance(step, LoopStep) and step.max_iterations > requested.max_loop_iterations:
            errors.append(
                f"loop {step.id} max_iterations exceeds harness max_loop_iterations"
            )
        if isinstance(step, ParallelStep) and len(step.branches) > requested.max_parallelism:
            errors.append(f"parallel step {step.id} exceeds harness max_parallelism")


def _validate_graph(harness: ProgressiveHarness, errors: list[str]) -> None:
    ids = {step.id for step in harness.steps}
    dependencies = {step.id: set(step.depends_on) for step in harness.steps}
    for step_id, parents in dependencies.items():
        missing = parents - ids
        if missing:
            errors.append(f"step {step_id} has unknown dependencies: {sorted(missing)}")
        if step_id in parents:
            errors.append(f"step {step_id} cannot depend on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            errors.append(f"dependency cycle includes step {step_id}")
            return
        if step_id in visited:
            return
        visiting.add(step_id)
        for parent in dependencies.get(step_id, set()):
            if parent in ids:
                visit(parent)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in ids:
        visit(step_id)

    finalizers = [step for step in harness.steps if step.kind == "finalize"]
    if len(finalizers) == 1:
        ancestors: set[str] = set()

        def collect_ancestors(step_id: str) -> None:
            for parent in dependencies.get(step_id, set()):
                if parent in ids and parent not in ancestors:
                    ancestors.add(parent)
                    collect_ancestors(parent)

        collect_ancestors(finalizers[0].id)
        disconnected = ids - ancestors - {finalizers[0].id}
        if disconnected:
            errors.append(f"steps do not contribute to finalize: {sorted(disconnected)}")


def _validate_required_steps(harness: ProgressiveHarness, errors: list[str]) -> None:
    gates = [step for step in harness.steps if isinstance(step, RuntimeGateStep)]
    reviews = [step for step in harness.steps if isinstance(step, ReviewStep)]
    finalizers = [step for step in harness.steps if step.kind == "finalize"]
    if not gates:
        errors.append("harness requires a runtime_gate step")
    if not reviews:
        errors.append("harness requires an independent review step")
    if len(finalizers) != 1:
        errors.append("harness requires exactly one finalize step")


def _validate_independence(harness: ProgressiveHarness, errors: list[str]) -> None:
    agent_steps = {step.id for step in harness.steps if isinstance(step, AgentCallStep)}
    for review in (step for step in harness.steps if isinstance(step, ReviewStep)):
        exclusions = set(review.selector.exclude_agents_from)
        if not exclusions:
            errors.append(f"review {review.id} must exclude an executor binding")
            continue
        unknown = exclusions - agent_steps
        if unknown:
            errors.append(f"review {review.id} excludes unknown agent steps: {sorted(unknown)}")


def _validate_agent_run_bound(harness: ProgressiveHarness, errors: list[str]) -> None:
    estimated_runs = 0
    for step in harness.steps:
        if isinstance(step, (AgentCallStep, ReviewStep)):
            estimated_runs += 1
        elif isinstance(step, ParallelStep):
            estimated_runs += len(step.branches)
        elif isinstance(step, LoopStep):
            estimated_runs += step.max_iterations * 2
    if estimated_runs > harness.bounds.max_agent_runs:
        errors.append(
            f"static agent run upper bound {estimated_runs} exceeds max_agent_runs "
            f"{harness.bounds.max_agent_runs}"
        )


def _validate_loop_references(harness: ProgressiveHarness, errors: list[str]) -> None:
    steps = {step.id: step for step in harness.steps}
    for loop in (step for step in harness.steps if isinstance(step, LoopStep)):
        if len(loop.id) > 84:
            errors.append(f"loop {loop.id} id is too long for physical iteration tasks")
        if len(loop.depends_on) != 1 or not isinstance(
            steps.get(loop.depends_on[0]) if loop.depends_on else None, ReviewStep
        ):
            errors.append(f"loop {loop.id} must depend on exactly one review step")
        binding_ref = loop.body.agent_call.selector.prefer_binding_from
        if binding_ref is not None and not isinstance(steps.get(binding_ref), AgentCallStep):
            errors.append(f"loop {loop.id} prefers unknown agent binding {binding_ref}")
        gate_ref = loop.body.runtime_gate.inherit_from
        if not isinstance(steps.get(gate_ref), RuntimeGateStep):
            errors.append(f"loop {loop.id} inherits unknown runtime gate {gate_ref}")
        review_ref = loop.body.review.inherit_from
        if not isinstance(steps.get(review_ref), ReviewStep):
            errors.append(f"loop {loop.id} inherits unknown review {review_ref}")
