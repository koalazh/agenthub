from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from agenthub.db.models import ApprovalRecord, ArtifactRecord, EventRecord, GoalRecord
from agenthub.db.repositories import _append_event
from agenthub.workspace.manager import CandidateCommit, WorkspaceManager


class ApprovalError(ValueError):
    pass


def resolve_approval(
    session: Session,
    *,
    goal_id: str,
    approval_id: str,
    decision: str,
    comment: str | None,
) -> ApprovalRecord:
    approval = session.get(ApprovalRecord, approval_id)
    if approval is None or approval.goal_id != goal_id:
        raise ApprovalError("approval not found")
    status = "approved" if decision == "approve" else "rejected"
    if approval.status != "pending":
        if approval.status == status:
            return approval
        raise ApprovalError(f"approval is already {approval.status}")
    approval.status = status
    approval.decision_json = {"decision": decision, "comment": comment}
    approval.resolved_at = datetime.now(UTC)
    _append_event(
        session,
        goal_id=goal_id,
        event_type=f"approval.{status}",
        actor="local-user",
        payload={"approval_id": approval.id, "type": approval.type},
        correlation_id=approval.id,
    )
    session.commit()
    return approval


def merge_goal(
    session: Session,
    *,
    goal_id: str,
    workspace_manager: WorkspaceManager,
) -> dict[str, str]:
    goal = session.get(GoalRecord, goal_id)
    if goal is None:
        raise ApprovalError("goal not found")
    if goal.status != "completed":
        raise ApprovalError("goal must be completed before merge")
    approval = session.scalar(
        select(ApprovalRecord).where(
            ApprovalRecord.goal_id == goal_id,
            ApprovalRecord.type == "merge",
            ApprovalRecord.status == "approved",
        )
    )
    if approval is None:
        raise ApprovalError("merge approval is required")
    prior = session.scalar(
        select(EventRecord).where(
            EventRecord.goal_id == goal_id, EventRecord.type == "merge.completed"
        )
    )
    if prior is not None:
        return {"status": "merged", "commit_sha": str(prior.payload_json["commit_sha"])}
    artifact = session.scalar(
        select(ArtifactRecord)
        .where(ArtifactRecord.goal_id == goal_id, ArtifactRecord.kind == "candidate_commit")
        .order_by(ArtifactRecord.created_at.desc())
    )
    if artifact is None:
        raise ApprovalError("candidate Commit Artifact is missing")
    metadata = artifact.metadata_json
    required = {"workspace_path", "branch", "base_commit", "commit_sha", "changed_files"}
    if metadata.get("fake") or not required.issubset(metadata):
        raise ApprovalError("candidate Commit is not backed by a verified Git Worktree")
    candidate = CandidateCommit(
        workspace_path=Path(str(metadata["workspace_path"])),
        branch=str(metadata["branch"]),
        base_commit=str(metadata["base_commit"]),
        commit_sha=str(metadata["commit_sha"]),
        changed_files=tuple(str(item) for item in metadata["changed_files"]),
    )
    merged_sha = workspace_manager.merge_candidate(
        project_root=Path(goal.project_root),
        default_branch=goal.default_branch,
        candidate=candidate,
    )
    _append_event(
        session,
        goal_id=goal_id,
        event_type="merge.completed",
        actor="agenthub://runtime",
        payload={"commit_sha": merged_sha, "approval_id": approval.id},
        correlation_id=approval.id,
    )
    session.commit()
    return {"status": "merged", "commit_sha": merged_sha}
