from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from agenthub.delivery.service import ApprovalError, merge_goal, resolve_approval

router = APIRouter(prefix="/api/goals", tags=["approvals"])


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    comment: str | None = None


@router.post("/{goal_id}/approvals/{approval_id}")
def decide_approval(
    goal_id: str,
    approval_id: str,
    payload: ApprovalDecisionRequest,
    request: Request,
) -> dict[str, object]:
    try:
        with request.app.state.session_factory() as session:
            approval = resolve_approval(
                session,
                goal_id=goal_id,
                approval_id=approval_id,
                decision=payload.decision,
                comment=payload.comment,
            )
            return {
                "approval_id": approval.id,
                "status": approval.status,
                "decision": approval.decision_json,
            }
    except ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{goal_id}/merge")
def merge_candidate(goal_id: str, request: Request) -> dict[str, str]:
    try:
        with request.app.state.session_factory() as session:
            return merge_goal(
                session,
                goal_id=goal_id,
                workspace_manager=request.app.state.workspace_manager,
            )
    except (ApprovalError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
