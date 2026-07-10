import asyncio
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from agenthub.api.dependencies import get_session
from agenthub.db.repositories import (
    GoalNotFoundError,
    HarnessVersionConflictError,
    create_goal,
    get_goal_detail,
    link_goal_session,
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


def encode_sse_events(
    events: list[dict[str, object]], cursor: int
) -> tuple[list[str], int]:
    messages: list[str] = []
    for event in events:
        event_id = int(event["id"])
        if event_id <= cursor:
            continue
        cursor = event_id
        messages.append(
            f"id: {cursor}\n"
            f"event: {event['type']}\n"
            f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"
        )
    return messages, cursor


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
    origin: "GoalOrigin | None" = None


class GoalOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, max_length=64)
    session_key: str = Field(min_length=1, max_length=300)
    external_user_id: str | None = Field(default=None, max_length=200)


class AttachSessionRequest(GoalOrigin):
    relation: str = Field(default="attached", pattern=r"^(origin|attached|delivery)$")


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
    if request.origin is not None:
        link_goal_session(
            session,
            goal_id=goal.id,
            session_key=request.origin.session_key,
            channel=request.origin.channel,
            external_user_id=request.origin.external_user_id,
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


@router.post("/{goal_id}/sessions", status_code=status.HTTP_201_CREATED)
def attach_goal_session(
    goal_id: str, payload: AttachSessionRequest, session: SessionDependency
) -> dict[str, object]:
    try:
        get_goal_detail(session, goal_id)
    except GoalNotFoundError as exc:
        raise _not_found(exc) from exc
    link = link_goal_session(
        session,
        goal_id=goal_id,
        session_key=payload.session_key,
        channel=payload.channel,
        external_user_id=payload.external_user_id,
        relation=payload.relation,
    )
    return {"id": link.id, "goal_id": goal_id, "session_key": link.session_key}


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
async def list_events_endpoint(
    goal_id: str,
    request: Request,
    session: SessionDependency,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
) -> object:
    try:
        events = list_events(session, goal_id)
    except GoalNotFoundError as exc:
        raise _not_found(exc) from exc
    if "text/event-stream" not in request.headers.get("accept", ""):
        return events

    async def stream():
        cursor = last_event_id or 0
        while True:
            with request.app.state.session_factory() as polling_session:
                current = list_events(polling_session, goal_id)
            messages, cursor = encode_sse_events(current, cursor)
            for message in messages:
                yield message
            if await request.is_disconnected():
                return
            if not messages:
                yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
