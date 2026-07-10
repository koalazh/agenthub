import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from agenthub.db.models import EventRecord, GoalRecord, HarnessVersionRecord
from agenthub.domain.goal import DeliveryMode, DeliveryPolicy, Goal, GoalContract, GoalStatus
from agenthub.harness.compiler import compile_harness
from agenthub.harness.patcher import PatchHarnessProposal, apply_patch
from agenthub.harness.schema import ProgressiveHarness
from agenthub.harness.validator import validate_harness


class GoalNotFoundError(LookupError):
    pass


class HarnessVersionConflictError(ValueError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _semantic_hash(contract: GoalContract) -> str:
    canonical = json.dumps(
        contract.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _append_event(
    session: Session,
    *,
    goal_id: str,
    event_type: str,
    actor: str,
    payload: dict[str, object],
    correlation_id: str,
) -> EventRecord:
    event = EventRecord(
        goal_id=goal_id,
        type=event_type,
        actor=actor,
        payload_json=payload,
        correlation_id=correlation_id,
        created_at=datetime.now(UTC),
    )
    session.add(event)
    return event


def create_goal(
    session: Session,
    *,
    objective: str,
    project_root: Path,
    acceptance_criteria: tuple[str, ...],
    constraints: tuple[str, ...],
    prohibited_actions: tuple[str, ...],
    required_evidence: tuple[str, ...],
    delivery_mode: DeliveryMode,
    owner_user_id: str,
    default_branch: str,
) -> Goal:
    now = datetime.now(UTC)
    goal = Goal(
        id=_id("goal"),
        title=objective.strip().splitlines()[0][:200],
        owner_user_id=owner_user_id,
        project_root=project_root,
        default_branch=default_branch,
        contract=GoalContract(
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            constraints=constraints,
            prohibited_actions=prohibited_actions,
            required_evidence=required_evidence,
            delivery=DeliveryPolicy(mode=delivery_mode),
        ),
        created_at=now,
        updated_at=now,
    )
    record = GoalRecord(
        id=goal.id,
        title=goal.title,
        objective=goal.contract.objective,
        status=goal.status,
        owner_user_id=goal.owner_user_id,
        project_root=str(goal.project_root),
        default_branch=goal.default_branch,
        delivery_mode=goal.contract.delivery.mode,
        contract_json=goal.contract.model_dump(mode="json"),
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )
    session.add(record)
    _append_event(
        session,
        goal_id=goal.id,
        event_type="goal.created",
        actor=owner_user_id,
        payload={"status": goal.status},
        correlation_id=_id("corr"),
    )
    session.commit()
    return goal


def get_goal_record(session: Session, goal_id: str) -> GoalRecord:
    record = session.get(GoalRecord, goal_id)
    if record is None:
        raise GoalNotFoundError(goal_id)
    return record


def goal_to_domain(record: GoalRecord) -> Goal:
    return Goal(
        id=record.id,
        title=record.title,
        status=GoalStatus(record.status),
        owner_user_id=record.owner_user_id,
        project_root=Path(record.project_root),
        default_branch=record.default_branch,
        contract=GoalContract.model_validate(record.contract_json),
        created_at=_utc(record.created_at),
        updated_at=_utc(record.updated_at),
    )


def list_goals(session: Session) -> list[Goal]:
    records = session.scalars(select(GoalRecord).order_by(GoalRecord.created_at.desc())).all()
    return [goal_to_domain(record) for record in records]


def submit_initial_harness(
    session: Session,
    *,
    goal_id: str,
    harness: ProgressiveHarness,
    generated_by: str,
) -> HarnessVersionRecord:
    goal_record = get_goal_record(session, goal_id)
    if goal_record.harness_versions:
        raise HarnessVersionConflictError("initial harness already exists; submit a patch")
    validate_harness(harness, goal_id=goal_id)
    return _commit_harness_version(
        session,
        goal_record=goal_record,
        harness=harness,
        parent=None,
        patch_reason="initial_plan",
        generated_by=generated_by,
    )


def patch_harness(
    session: Session,
    *,
    goal_id: str,
    proposal: PatchHarnessProposal,
) -> HarnessVersionRecord:
    goal_record = get_goal_record(session, goal_id)
    current = session.scalar(
        select(HarnessVersionRecord)
        .where(
            HarnessVersionRecord.goal_id == goal_id,
            HarnessVersionRecord.status == "active",
        )
        .order_by(HarnessVersionRecord.version.desc())
    )
    if current is None:
        raise HarnessVersionConflictError("goal has no active harness to patch")
    if current.version != proposal.base_version:
        raise HarnessVersionConflictError(
            f"base_version {proposal.base_version} is stale; active version is {current.version}"
        )
    contract = GoalContract.model_validate(goal_record.contract_json)
    if current.semantic_hash != _semantic_hash(contract):
        raise HarnessVersionConflictError("active harness semantic contract hash is stale")
    current_harness = ProgressiveHarness.model_validate(current.logical_ir_json)
    patches_used = current.version - 1
    if patches_used >= current_harness.bounds.max_patch_versions:
        raise HarnessVersionConflictError("harness patch version limit has been reached")
    patched = apply_patch(current_harness, proposal)
    validate_harness(patched, goal_id=goal_id)
    return _commit_harness_version(
        session,
        goal_record=goal_record,
        harness=patched,
        parent=current,
        patch_reason=proposal.reason,
        generated_by=proposal.generated_by,
    )


def _commit_harness_version(
    session: Session,
    *,
    goal_record: GoalRecord,
    harness: ProgressiveHarness,
    parent: HarnessVersionRecord | None,
    patch_reason: str,
    generated_by: str,
) -> HarnessVersionRecord:
    contract = GoalContract.model_validate(goal_record.contract_json)
    version = 1 if parent is None else parent.version + 1
    correlation_id = _id("corr")
    record = HarnessVersionRecord(
        id=_id("hv"),
        goal_id=goal_record.id,
        version=version,
        parent_version_id=parent.id if parent else None,
        status="active",
        logical_ir_json=harness.model_dump(mode="json"),
        compilation_json=compile_harness(harness).model_dump(mode="json"),
        semantic_hash=_semantic_hash(contract),
        patch_reason=patch_reason,
        generated_by=generated_by,
        created_at=datetime.now(UTC),
    )
    if parent is not None:
        parent.status = "superseded"
    session.add(record)
    for event_type in ("harness.proposed", "harness.validated", "harness.activated"):
        _append_event(
            session,
            goal_id=goal_record.id,
            event_type=event_type,
            actor=generated_by,
            payload={"harness_version_id": record.id, "version": version},
            correlation_id=correlation_id,
        )
    if GoalStatus(goal_record.status) is GoalStatus.DRAFT:
        domain_goal = goal_to_domain(goal_record).transition_to(
            GoalStatus.PLANNED, actor="runtime"
        )
        goal_record.status = domain_goal.status
        goal_record.updated_at = domain_goal.updated_at
    session.commit()
    session.refresh(record)
    return record


def serialize_harness_version(record: HarnessVersionRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "version": record.version,
        "parent_version_id": record.parent_version_id,
        "status": record.status,
        "logical_ir": record.logical_ir_json,
        "compilation": record.compilation_json,
        "semantic_hash": record.semantic_hash,
        "patch_reason": record.patch_reason,
        "generated_by": record.generated_by,
        "created_at": _utc(record.created_at),
    }


def get_goal_detail(session: Session, goal_id: str) -> dict[str, object]:
    record = get_goal_record(session, goal_id)
    goal = goal_to_domain(record)
    versions = session.scalars(
        select(HarnessVersionRecord)
        .where(HarnessVersionRecord.goal_id == goal_id)
        .order_by(HarnessVersionRecord.version)
    ).all()
    return {
        "goal": goal.model_dump(mode="json"),
        "harness_versions": [serialize_harness_version(version) for version in versions],
        "current_harness_version": next(
            (
                serialize_harness_version(version)
                for version in reversed(versions)
                if version.status == "active"
            ),
            None,
        ),
    }


def list_events(session: Session, goal_id: str) -> list[dict[str, object]]:
    get_goal_record(session, goal_id)
    events = session.scalars(
        select(EventRecord).where(EventRecord.goal_id == goal_id).order_by(EventRecord.id)
    ).all()
    return [
        {
            "id": event.id,
            "goal_id": event.goal_id,
            "type": event.type,
            "actor": event.actor,
            "payload": event.payload_json,
            "correlation_id": event.correlation_id,
            "created_at": _utc(event.created_at),
        }
        for event in events
    ]
