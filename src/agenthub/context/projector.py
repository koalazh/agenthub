from pathlib import Path

from agenthub.context.task_envelope import (
    EscalationPolicy,
    GoalContext,
    OutputContract,
    Permissions,
    TaskConstraints,
    TaskEnvelope,
    TaskIdentity,
    TaskInputs,
    TaskObjective,
)
from agenthub.domain.goal import Goal
from agenthub.harness.schema import AgentCallStep, ReviewStep


def project_task_envelope(
    *,
    goal: Goal,
    run_id: str,
    step: AgentCallStep | ReviewStep,
    workspace_path: Path,
    handoff_refs: tuple[str, ...] = (),
    artifact_refs: tuple[str, ...] = (),
) -> TaskEnvelope:
    is_review = isinstance(step, ReviewStep)
    can_write = isinstance(step, AgentCallStep) and step.workspace.mode == "write_candidate"
    statement = (
        "Independently review the candidate result and evidence" if is_review else step.task
    )
    return TaskEnvelope(
        identity=TaskIdentity(
            goal_id=goal.id,
            task_id=step.id,
            run_id=run_id,
            role="reviewer" if is_review else "worker",
        ),
        objective=TaskObjective(statement=statement),
        goal_context=GoalContext(summary=goal.contract.objective, relevance=step.id),
        acceptance_criteria=goal.contract.acceptance_criteria,
        inputs=TaskInputs(handoffs=handoff_refs, artifacts=artifact_refs),
        constraints=TaskConstraints(
            permissions=Permissions(
                repository="write_candidate" if can_write else "read_only",
                network="deny",
            ),
            prohibited_actions=goal.contract.prohibited_actions,
        ),
        output_contract=OutputContract(
            kind="review" if is_review else "worker_result",
            artifact_dir=str(workspace_path),
            artifacts=step.outputs,
        ),
        escalation=EscalationPolicy(
            allowed_proposals=(
                "request_context",
                "request_capability",
                "spawn_task",
                "report_blocker",
            )
        ),
    )
