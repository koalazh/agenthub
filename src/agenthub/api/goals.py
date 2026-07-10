from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from agenthub.api.dependencies import get_session
from agenthub.db.repositories import (
    GoalNotFoundError,
    HarnessVersionConflictError,
    create_goal,
    get_goal_detail,
    list_events,
    list_goals,
    patch_harness,
    serialize_harness_version,
    submit_initial_harness,
)
from agenthub.domain.goal import DeliveryMode
from agenthub.harness.patcher import HarnessPatchError, parse_patch
from agenthub.harness.validator import HarnessValidationError, parse_harness

router = APIRouter(prefix="/api/goals", tags=["goals"])
SessionDependency = Annotated[Session, Depends(get_session)]


class CreateGoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1)
    project_root: Path
    acceptance_criteria: tuple[str, ...] = Field(min_length=1)
    constraints: tuple[str, ...] = ()
    prohibited_actions: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] | None = None
    delivery_mode: DeliveryMode = DeliveryMode.CANDIDATE_COMMIT
    owner_user_id: str = "local-user"
    default_branch: str = "main"


def _not_found(exc: GoalNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"goal {exc} not found")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_goal_endpoint(
    request: CreateGoalRequest, session: SessionDependency
) -> dict[str, object]:
    evidence = request.required_evidence or request.acceptance_criteria
    goal = create_goal(
        session,
        objective=request.objective,
        project_root=request.project_root.resolve(),
        acceptance_criteria=request.acceptance_criteria,
        constraints=request.constraints,
        prohibited_actions=request.prohibited_actions,
        required_evidence=evidence,
        delivery_mode=request.delivery_mode,
        owner_user_id=request.owner_user_id,
        default_branch=request.default_branch,
    )
    return {"goal_id": goal.id, "status": goal.status, "contract": goal.contract}


@router.get("")
def list_goals_endpoint(session: SessionDependency) -> list[dict[str, object]]:
    return [goal.model_dump(mode="json") for goal in list_goals(session)]


@router.get("/{goal_id}")
def get_goal_endpoint(goal_id: str, session: SessionDependency) -> dict[str, object]:
    try:
        return get_goal_detail(session, goal_id)
    except GoalNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/{goal_id}/harness", status_code=status.HTTP_201_CREATED)
def submit_harness_endpoint(
    goal_id: str,
    session: SessionDependency,
    payload: Annotated[dict[str, object], Body()],
) -> dict[str, object]:
    try:
        harness = parse_harness(payload)
        record = submit_initial_harness(
            session,
            goal_id=goal_id,
            harness=harness,
            generated_by="hermes://agenthub-hub",
        )
        return serialize_harness_version(record)
    except GoalNotFoundError as exc:
        raise _not_found(exc) from exc
    except HarnessValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except HarnessVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{goal_id}/harness/patch", status_code=status.HTTP_201_CREATED)
def patch_harness_endpoint(
    goal_id: str,
    session: SessionDependency,
    payload: Annotated[dict[str, object], Body()],
) -> dict[str, object]:
    try:
        proposal = parse_patch(payload)
        record = patch_harness(session, goal_id=goal_id, proposal=proposal)
        return serialize_harness_version(record)
    except GoalNotFoundError as exc:
        raise _not_found(exc) from exc
    except HarnessValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except HarnessPatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HarnessVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{goal_id}/events")
def list_events_endpoint(goal_id: str, session: SessionDependency) -> list[dict[str, object]]:
    try:
        return list_events(session, goal_id)
    except GoalNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/{goal_id}/execute")
async def execute_goal_endpoint(goal_id: str, request: Request) -> dict[str, object]:
    controller = request.app.state.runtime_controller
    if controller is None:
        raise HTTPException(
            status_code=503,
            detail=request.app.state.runtime_error or "Hermes Runtime is unavailable",
        )
    try:
        return await controller.run_fake_until_terminal(goal_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{goal_id}/cancel")
def cancel_goal_endpoint(goal_id: str, request: Request) -> dict[str, object]:
    controller = request.app.state.runtime_controller
    if controller is None:
        raise HTTPException(
            status_code=503,
            detail=request.app.state.runtime_error or "Hermes Runtime is unavailable",
        )
    try:
        return controller.cancel_goal(goal_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
