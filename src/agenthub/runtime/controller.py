import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from agenthub.artifacts.store import ArtifactProvenance, ArtifactStore
from agenthub.context.handoff import Handoff
from agenthub.context.projector import project_task_envelope
from agenthub.db.models import (
    AgentStatsRecord,
    ApprovalRecord,
    ArtifactRecord,
    GoalRecord,
    HandoffRecord,
    HarnessRunRecord,
    HarnessVersionRecord,
    StepExecutionRecord,
    TaskMappingRecord,
    UsageRecord,
)
from agenthub.db.repositories import _append_event, get_goal_detail, goal_to_domain
from agenthub.domain.goal import GoalStatus
from agenthub.gates.runner import GateRunner
from agenthub.harness.compiler import PhysicalStep, compile_harness, resolve_physical_step
from agenthub.harness.schema import (
    AgentCallStep,
    FinalizeStep,
    LoopStep,
    ParallelStep,
    ProgressiveHarness,
    ReviewStep,
    RuntimeGateStep,
    WaitApprovalStep,
)
from agenthub.hermes.kanban_adapter import HermesKanbanAdapter, task_body
from agenthub.registry.models import AgentDefinition, AgentRegistryConfig
from agenthub.registry.resolver import AgentDemand, resolve_agent
from agenthub.workers.base import (
    ProducedArtifact,
    WorkerEvent,
    WorkerResult,
    WorkerResultStatus,
    WorkerStartRequest,
)
from agenthub.workers.fake_adapter import FakeWorkerAdapter
from agenthub.workers.hermes_adapter import HermesProfileWorkerAdapter
from agenthub.workers.supervisor import ExternalLaneSupervisor
from agenthub.workspace.manager import WorkspaceError, WorkspaceManager


class RuntimeExecutionError(RuntimeError):
    pass


class RuntimeController:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        kanban: HermesKanbanAdapter,
        artifacts: ArtifactStore,
        workspaces: WorkspaceManager,
        fake_worker: FakeWorkerAdapter | None = None,
        gate_runner: GateRunner | None = None,
        registry: AgentRegistryConfig | None = None,
        available_runtimes: frozenset[str] = frozenset(),
        default_worker_lane: str = "fake",
        external_supervisor: ExternalLaneSupervisor | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._kanban = kanban
        self._artifacts = artifacts
        self._workspaces = workspaces
        self._fake_worker = fake_worker or FakeWorkerAdapter()
        self._gate_runner = gate_runner or GateRunner()
        self._registry = registry
        self._available_runtimes = available_runtimes
        self._default_worker_lane = default_worker_lane
        self._external_supervisor = external_supervisor
        self._hermes_spawn_fn = None

    def start_goal(self, goal_id: str) -> str:
        with self._session_factory() as session:
            goal = session.get(GoalRecord, goal_id)
            if goal is None:
                raise RuntimeExecutionError(f"goal {goal_id} not found")
            version = session.scalar(
                select(HarnessVersionRecord).where(
                    HarnessVersionRecord.goal_id == goal_id,
                    HarnessVersionRecord.status == "active",
                )
            )
            if version is None:
                raise RuntimeExecutionError("goal has no active harness")
            harness = ProgressiveHarness.model_validate(version.logical_ir_json)
            run = session.scalar(
                select(HarnessRunRecord).where(
                    HarnessRunRecord.goal_id == goal_id,
                    HarnessRunRecord.status.in_(("pending", "running", "waiting")),
                )
            )
            if run is None:
                run = HarnessRunRecord(
                    id=f"hr_{uuid4().hex}",
                    goal_id=goal_id,
                    harness_version_id=version.id,
                    status="pending",
                    current_phase=None,
                    checkpoint_json={},
                    started_at=datetime.now(UTC),
                    ended_at=None,
                )
                session.add(run)
                for step in compile_harness(harness).steps:
                    session.add(
                        StepExecutionRecord(
                            id=f"se_{uuid4().hex}",
                            harness_run_id=run.id,
                            step_id=step.id,
                            kind=step.kind,
                            status="pending",
                            attempt=1,
                            kanban_task_id=None,
                            agent_id=None,
                            started_at=None,
                            ended_at=None,
                            result_json={},
                        )
                    )
                session.commit()
            run_id = run.id

        self._materialize(run_id)
        return run_id

    def recover_active_runs(self) -> list[str]:
        with self._session_factory() as session:
            run_ids = list(
                session.scalars(
                    select(HarnessRunRecord.id).where(
                        HarnessRunRecord.status.in_(("pending", "running", "waiting"))
                    )
                )
            )
        for run_id in run_ids:
            self._materialize(run_id)
        return run_ids

    def cancel_goal(self, goal_id: str) -> dict[str, object]:
        with self._session_factory() as session:
            goal = session.get(GoalRecord, goal_id)
            if goal is None:
                raise RuntimeExecutionError(f"goal {goal_id} not found")
            run = session.scalar(
                select(HarnessRunRecord).where(
                    HarnessRunRecord.goal_id == goal_id,
                    HarnessRunRecord.status.in_(("pending", "running", "waiting")),
                )
            )
            if run is not None:
                mappings = session.scalars(
                    select(TaskMappingRecord).where(TaskMappingRecord.harness_run_id == run.id)
                ).all()
                for mapping in mappings:
                    self._kanban.archive(
                        board=mapping.kanban_board, task_id=mapping.kanban_task_id
                    )
                executions = session.scalars(
                    select(StepExecutionRecord).where(
                        StepExecutionRecord.harness_run_id == run.id,
                        StepExecutionRecord.status.in_(("pending", "running")),
                    )
                ).all()
                for execution in executions:
                    execution.status = "canceled"
                    execution.ended_at = datetime.now(UTC)
                run.status = "canceled"
                run.ended_at = datetime.now(UTC)
            domain_goal = goal_to_domain(goal)
            if domain_goal.status not in {
                GoalStatus.COMPLETED,
                GoalStatus.FAILED,
                GoalStatus.CANCELED,
            }:
                domain_goal = domain_goal.transition_to(GoalStatus.CANCELED, actor="runtime")
                goal.status = domain_goal.status
                goal.updated_at = domain_goal.updated_at
            _append_event(
                session,
                goal_id=goal.id,
                event_type="goal.canceled",
                actor="agenthub://runtime",
                payload={"harness_run_id": run.id if run else None},
                correlation_id=run.id if run else goal.id,
            )
            session.commit()
            return get_goal_detail(session, goal_id)

    def _materialize(self, run_id: str) -> None:
        with self._session_factory() as session:
            run = session.get(HarnessRunRecord, run_id)
            if run is None:
                raise RuntimeExecutionError(f"harness run {run_id} not found")
            goal = session.get(GoalRecord, run.goal_id)
            version = session.get(HarnessVersionRecord, run.harness_version_id)
            if goal is None or version is None:
                raise RuntimeExecutionError("run references missing goal or harness version")
            harness = ProgressiveHarness.model_validate(version.logical_ir_json)
            board = self._kanban.ensure_board(project_root=Path(goal.project_root))
            ordered = compile_harness(harness).steps

            for physical in ordered:
                existing = session.scalar(
                    select(TaskMappingRecord).where(
                        TaskMappingRecord.harness_run_id == run.id,
                        TaskMappingRecord.step_id == physical.id,
                    )
                )
                if existing is not None:
                    continue
                step = resolve_physical_step(harness, physical)
                parent_mappings = [
                    session.scalar(
                        select(TaskMappingRecord).where(
                            TaskMappingRecord.harness_run_id == run.id,
                            TaskMappingRecord.step_id == parent,
                        )
                    )
                    for parent in physical.depends_on
                ]
                if any(parent is None for parent in parent_mappings):
                    raise RuntimeExecutionError(f"step {step.id} parent mapping is missing")
                parent_ids = tuple(parent.kanban_task_id for parent in parent_mappings if parent)
                workspace_kind, workspace_path, branch_name, base_commit = (
                    self._workspace_for_step(
                        step=step,
                        goal=goal,
                        parent_mappings=[parent for parent in parent_mappings if parent],
                        reuse_parent_workspace=physical.loop_phase == "repair",
                    )
                )
                outputs = self._outputs(step)
                binding = self._binding_for_step(session, run, step)
                task_id = self._kanban.create_task(
                    board=board,
                    title=f"{goal.title}: {step.id}",
                    body=task_body(
                        goal_id=goal.id,
                        harness_version=version.version,
                        step_id=step.id,
                        objective=self._objective(step),
                        acceptance_criteria=tuple(
                            goal.contract_json.get("acceptance_criteria", [])
                        ),
                        output_contract=outputs,
                    ),
                    assignee=self._assignee(binding, step),
                    parents=parent_ids,
                    idempotency_key=f"{goal.id}:{version.version}:{step.id}:1",
                    workspace_kind=workspace_kind,
                    workspace_path=workspace_path,
                    branch_name=branch_name if workspace_kind == "worktree" else None,
                    max_runtime_seconds=harness.bounds.max_wall_time_seconds,
                )
                execution = session.scalar(
                    select(StepExecutionRecord).where(
                        StepExecutionRecord.harness_run_id == run.id,
                        StepExecutionRecord.step_id == step.id,
                        StepExecutionRecord.attempt == 1,
                    )
                )
                if execution is None:
                    raise RuntimeExecutionError(f"step execution {step.id} is missing")
                execution.kanban_task_id = task_id
                execution.agent_id = (
                    binding.id if binding is not None else self._fake_agent_id(step)
                )
                session.add(
                    TaskMappingRecord(
                        id=f"tm_{uuid4().hex}",
                        goal_id=goal.id,
                        harness_version_id=version.id,
                        harness_run_id=run.id,
                        step_id=step.id,
                        kanban_board=board,
                        kanban_task_id=task_id,
                        expected_run_id=None,
                        workspace_path=workspace_path,
                        branch_name=branch_name,
                        base_commit=base_commit,
                    )
                )
                _append_event(
                    session,
                    goal_id=goal.id,
                    event_type="step.materialized",
                    actor="agenthub://runtime",
                    payload={"step_id": step.id, "kanban_task_id": task_id, "board": board},
                    correlation_id=run.id,
                )
                session.commit()

            if run.status == "pending":
                run.status = "running"
            domain_goal = goal_to_domain(goal)
            if domain_goal.status is GoalStatus.PLANNED:
                domain_goal = domain_goal.transition_to(GoalStatus.RUNNING, actor="runtime")
                goal.status = domain_goal.status
                goal.updated_at = domain_goal.updated_at
            session.commit()

    def _workspace_for_step(
        self,
        *,
        step: object,
        goal: GoalRecord,
        parent_mappings: list[TaskMappingRecord],
        reuse_parent_workspace: bool = False,
    ) -> tuple[str, str | None, str | None, str | None]:
        project_root = Path(goal.project_root)
        if (
            isinstance(step, AgentCallStep)
            and step.workspace.mode == "write_candidate"
            and not reuse_parent_workspace
        ):
            workspace = self._workspaces.provision(
                project_root=project_root,
                default_branch=goal.default_branch,
                goal_id=goal.id,
                task_id=step.id,
            )
            return "worktree", str(workspace.path), workspace.branch, workspace.base_commit
        for parent in reversed(parent_mappings):
            snapshot = self._kanban.get_task(
                board=parent.kanban_board, task_id=parent.kanban_task_id
            )
            if snapshot and snapshot.workspace_path:
                return (
                    "dir",
                    snapshot.workspace_path,
                    parent.branch_name,
                    parent.base_commit,
                )
        return "dir", str(project_root), None, None

    async def run_fake_until_terminal(
        self, goal_id: str, *, max_ticks: int = 50
    ) -> dict[str, object]:
        run_id = self.start_goal(goal_id)
        for _ in range(max_ticks):
            progressed = await self.tick(run_id)
            with self._session_factory() as session:
                run = session.get(HarnessRunRecord, run_id)
                if run and run.status in {"completed", "failed", "canceled"}:
                    return get_goal_detail(session, goal_id)
                if run and run.status == "waiting":
                    return get_goal_detail(session, goal_id)
            if not progressed:
                raise RuntimeExecutionError("harness run is stalled")
        raise RuntimeExecutionError("harness run exceeded controller tick limit")

    async def tick(self, run_id: str) -> bool:
        with self._session_factory() as session:
            run = session.get(HarnessRunRecord, run_id)
            if run is None or run.status != "running":
                return False
            version = session.get(HarnessVersionRecord, run.harness_version_id)
            goal = session.get(GoalRecord, run.goal_id)
            if version is None or goal is None:
                raise RuntimeExecutionError("run references missing state")
            harness = ProgressiveHarness.model_validate(version.logical_ir_json)
            plan = compile_harness(harness)
            progressed = False
            for physical in plan.steps:
                step_id = physical.id
                execution = session.scalar(
                    select(StepExecutionRecord).where(
                        StepExecutionRecord.harness_run_id == run.id,
                        StepExecutionRecord.step_id == step_id,
                        StepExecutionRecord.attempt == 1,
                    )
                )
                mapping = session.scalar(
                    select(TaskMappingRecord).where(
                        TaskMappingRecord.harness_run_id == run.id,
                        TaskMappingRecord.step_id == step_id,
                    )
                )
                if execution is None or mapping is None or execution.status != "pending":
                    continue
                task = self._kanban.get_task(
                    board=mapping.kanban_board, task_id=mapping.kanban_task_id
                )
                if task is None or task.status != "ready":
                    continue
                step = resolve_physical_step(harness, physical)
                if physical.loop_id and physical.loop_phase != "complete":
                    if self._should_skip_loop_step(session, run, physical):
                        self._skip_step(session, run, goal, execution, mapping)
                        progressed = True
                        continue
                if isinstance(step, (AgentCallStep, ReviewStep)):
                    await self._execute_worker(session, run, goal, step, execution, mapping)
                elif isinstance(step, RuntimeGateStep):
                    self._execute_gate(session, run, goal, step, execution, mapping)
                elif isinstance(step, FinalizeStep):
                    self._finalize(session, run, goal, step, execution, mapping)
                elif isinstance(step, LoopStep):
                    self._complete_loop(session, run, goal, step, execution, mapping)
                elif isinstance(step, ParallelStep):
                    self._complete_parallel(session, run, goal, step, execution, mapping)
                elif isinstance(step, WaitApprovalStep):
                    self._wait_for_approval(session, run, goal, step, execution, mapping)
                else:
                    raise RuntimeExecutionError(f"step kind {step.kind} is not executable yet")
                progressed = True
                if run.status != "running":
                    break
            return progressed

    async def _execute_worker(
        self,
        session: Session,
        run: HarnessRunRecord,
        goal: GoalRecord,
        step: AgentCallStep | ReviewStep,
        execution: StepExecutionRecord,
        mapping: TaskMappingRecord,
    ) -> None:
        hermes_lane = (execution.agent_id or "").startswith("hermes://")
        if hermes_lane:
            claimed = self._kanban.get_task(
                board=mapping.kanban_board, task_id=mapping.kanban_task_id
            )
            if claimed is None or claimed.status != "ready":
                return
            worker_run_id = 0
        else:
            claimed = self._kanban.claim_task(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                claimer=f"agenthub:{run.id}:{step.id}",
                ttl_seconds=900,
            )
            if claimed is None or claimed.current_run_id is None:
                return
            worker_run_id = claimed.current_run_id
            mapping.expected_run_id = worker_run_id
        execution.status = "running"
        execution.started_at = datetime.now(UTC)
        if isinstance(step, ReviewStep):
            domain_goal = goal_to_domain(goal)
            if domain_goal.status is GoalStatus.RUNNING:
                domain_goal = domain_goal.transition_to(GoalStatus.REVIEW, actor="runtime")
                goal.status = domain_goal.status
                goal.updated_at = domain_goal.updated_at
        session.commit()

        workspace_path = Path(claimed.workspace_path or goal.project_root)
        request = WorkerStartRequest(
            goal_id=goal.id,
            task_id=step.id,
            kanban_task_id=mapping.kanban_task_id,
            expected_run_id=worker_run_id,
            agent_id=execution.agent_id or "fake://default",
            task_envelope=self._task_envelope(session, goal, run, step, workspace_path),
            workspace_path=workspace_path,
            timeout_seconds=900,
            artifact_output_dir=self._artifacts.root / goal.id / step.id,
        )
        if (execution.agent_id or "").startswith("fake://"):
            handle = await self._fake_worker.start(request)
            events = [event async for event in self._fake_worker.stream_events(handle)]
            result = await self._fake_worker.collect_result(handle)
        elif (execution.agent_id or "").startswith(("claude://", "codex://")):
            if self._external_supervisor is None:
                raise RuntimeExecutionError("External Lane Supervisor is unavailable")
            supervised = await self._external_supervisor.run(request)
            events = list(supervised.events)
            result = supervised.result
        elif (execution.agent_id or "").startswith("hermes://"):
            events, result = await self._run_hermes_worker(request, mapping)
            terminal_event = next(
                (
                    event
                    for event in reversed(
                        self._kanban.list_events(
                            board=mapping.kanban_board,
                            task_id=mapping.kanban_task_id,
                        )
                    )
                    if event.run_id is not None
                ),
                None,
            )
            if terminal_event is None or terminal_event.run_id is None:
                raise RuntimeExecutionError("Hermes Worker did not produce a Run identity")
            worker_run_id = terminal_event.run_id
            mapping.expected_run_id = worker_run_id
        else:
            raise RuntimeExecutionError(f"unsupported Worker binding {execution.agent_id}")
        self._record_usage(session, run, execution, mapping, result)
        for event in events:
            _append_event(
                session,
                goal_id=goal.id,
                event_type=f"worker.{event.type}",
                actor=execution.agent_id or "fake://default",
                payload={"step_id": step.id, **event.payload},
                correlation_id=run.id,
            )
        if result.status is not WorkerResultStatus.COMPLETED:
            self._record_agent_stats(session, execution, step, result)
            if not hermes_lane:
                self._kanban.block(
                    board=mapping.kanban_board,
                    task_id=mapping.kanban_task_id,
                    expected_run_id=worker_run_id,
                    reason=f"worker-failed: {result.summary}",
                )
            self._fail_run(session, run, goal, execution, result.summary)
            return

        review_decision: str | None = None
        if isinstance(step, ReviewStep):
            try:
                review_decision = self._parse_review_decision(result.artifacts)
            except RuntimeExecutionError as exc:
                if not hermes_lane:
                    self._kanban.block(
                        board=mapping.kanban_board,
                        task_id=mapping.kanban_task_id,
                        expected_run_id=worker_run_id,
                        reason=f"review-invalid: {exc}",
                    )
                self._fail_run(session, run, goal, execution, str(exc))
                return

        candidate_metadata: dict[str, object] | None = None
        produced_artifacts = result.artifacts
        if (
            isinstance(step, AgentCallStep)
            and step.workspace.mode == "write_candidate"
            and not (execution.agent_id or "").startswith("fake://")
        ):
            if not (mapping.workspace_path and mapping.branch_name and mapping.base_commit):
                self._fail_run(session, run, goal, execution, "candidate workspace facts missing")
                return
            try:
                candidate = self._workspaces.inspect_candidate(
                    workspace_path=Path(mapping.workspace_path),
                    branch=mapping.branch_name,
                    base_commit=mapping.base_commit,
                )
            except WorkspaceError as exc:
                if not hermes_lane:
                    self._kanban.block(
                        board=mapping.kanban_board,
                        task_id=mapping.kanban_task_id,
                        expected_run_id=worker_run_id,
                        reason=f"candidate-invalid: {exc}",
                    )
                self._fail_run(session, run, goal, execution, str(exc))
                return
            candidate_metadata = {
                "workspace_path": str(candidate.workspace_path),
                "branch": candidate.branch,
                "base_commit": candidate.base_commit,
                "commit_sha": candidate.commit_sha,
                "changed_files": list(candidate.changed_files),
            }
            candidate_content = json.dumps(candidate_metadata, indent=2).encode()
            produced_artifacts = tuple(
                ProducedArtifact(
                    kind=artifact.kind,
                    filename=artifact.filename,
                    media_type=(
                        "application/json"
                        if artifact.kind == "candidate_commit"
                        else artifact.media_type
                    ),
                    content=(
                        candidate_content
                        if artifact.kind == "candidate_commit"
                        else artifact.content
                    ),
                )
                for artifact in result.artifacts
            )
        self._record_agent_stats(
            session, execution, step, result, review_decision=review_decision
        )

        artifact_uris: list[str] = []
        for produced in produced_artifacts:
            artifact_metadata: dict[str, object] = {"filename": produced.filename}
            if produced.kind == "candidate_commit":
                artifact_metadata.update(candidate_metadata or {"fake": True})
            record = self._artifacts.publish(
                session,
                provenance=ArtifactProvenance(
                    goal_id=goal.id,
                    task_id=step.id,
                    run_id=f"{mapping.kanban_board}:{worker_run_id}",
                    created_by_agent=execution.agent_id or "fake://default",
                ),
                kind=produced.kind,
                media_type=produced.media_type,
                content=produced.content,
                metadata=artifact_metadata,
            )
            artifact_uris.append(record.uri)
            _append_event(
                session,
                goal_id=goal.id,
                event_type="artifact.published",
                actor=execution.agent_id or "fake://default",
                payload={"step_id": step.id, "artifact_id": record.id, "kind": record.kind},
                correlation_id=run.id,
            )
        if not hermes_lane:
            if not self._kanban.complete(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                expected_run_id=worker_run_id,
                summary=result.summary,
                metadata={"artifacts": artifact_uris},
            ):
                self._fail_run(session, run, goal, execution, "stale worker completion rejected")
                return
        execution.status = "succeeded"
        execution.ended_at = datetime.now(UTC)
        result_json = result.model_dump(mode="json", exclude={"artifacts"})
        if review_decision is not None:
            result_json["review_decision"] = review_decision
        execution.result_json = result_json
        self._publish_handoffs(
            session,
            run=run,
            from_task_id=step.id,
            summary=result.summary,
            artifact_refs=tuple(artifact_uris),
        )
        event_type = "review.completed" if isinstance(step, ReviewStep) else "step.completed"
        payload: dict[str, object] = {"step_id": step.id}
        if isinstance(step, ReviewStep):
            payload["decision"] = review_decision
        _append_event(
            session,
            goal_id=goal.id,
            event_type=event_type,
            actor=execution.agent_id or "fake://default",
            payload=payload,
            correlation_id=run.id,
        )
        session.commit()

    async def _run_hermes_worker(
        self, request: WorkerStartRequest, mapping: TaskMappingRecord
    ) -> tuple[list[WorkerEvent], WorkerResult]:
        if self._registry is None:
            raise RuntimeExecutionError("Agent Registry is unavailable")
        definition = next(
            (agent for agent in self._registry.agents if agent.id == request.agent_id), None
        )
        if definition is None or definition.profile is None:
            raise RuntimeExecutionError(f"Hermes binding {request.agent_id} has no Profile")
        adapter = HermesProfileWorkerAdapter(
            kanban=self._kanban,
            board=mapping.kanban_board,
            agent_id=definition.id,
            profile=definition.profile,
            spawn_fn=self._hermes_spawn_fn,
        )
        handle = await adapter.start(request)
        events: list[WorkerEvent] = []
        deadline = asyncio.get_running_loop().time() + request.timeout_seconds
        terminal = {"done", "blocked", "archived", "crashed", "gave_up", "timed_out"}
        while True:
            events.extend([event async for event in adapter.stream_events(handle)])
            task = self._kanban.get_task(
                board=mapping.kanban_board, task_id=mapping.kanban_task_id
            )
            if task is None:
                raise RuntimeExecutionError("Hermes Worker task disappeared")
            if task.status in terminal:
                return events, await adapter.collect_result(handle)
            if asyncio.get_running_loop().time() >= deadline:
                await adapter.cancel(handle)
                return events, await adapter.collect_result(handle)
            await asyncio.sleep(0.1)

    @staticmethod
    def _record_agent_stats(
        session: Session,
        execution: StepExecutionRecord,
        step: AgentCallStep | ReviewStep,
        result: object,
        review_decision: str | None = None,
    ) -> None:
        if not execution.agent_id or execution.agent_id.startswith("fake://"):
            return
        stats = session.get(AgentStatsRecord, execution.agent_id)
        if stats is None:
            return
        now = datetime.now(UTC)
        prior_runs = stats.completed_runs + stats.recent_failure_count
        started = execution.started_at or now
        latency_ms = max(0.0, (now - started).total_seconds() * 1000)
        stats.average_latency_ms = (
            (stats.average_latency_ms * prior_runs + latency_ms) / (prior_runs + 1)
        )
        usage = getattr(result, "usage", {})
        cost = float(usage.get("cost_usd", 0.0)) if isinstance(usage, dict) else 0.0
        stats.average_cost = (stats.average_cost * prior_runs + cost) / (prior_runs + 1)
        if result.status is WorkerResultStatus.COMPLETED:
            stats.completed_runs += 1
            stats.recent_failure_count = 0
            if isinstance(step, ReviewStep):
                stats.verifier_total_count += 1
                if review_decision == "pass":
                    stats.verifier_pass_count += 1
        else:
            stats.recent_failure_count += 1
        stats.last_used_at = now

    @staticmethod
    def _record_usage(
        session: Session,
        run: HarnessRunRecord,
        execution: StepExecutionRecord,
        mapping: TaskMappingRecord,
        result: object,
    ) -> None:
        usage = getattr(result, "usage", {})
        if not isinstance(usage, dict):
            usage = {}

        def integer(name: str) -> int:
            value = usage.get(name, 0)
            return int(value) if isinstance(value, int | float) else 0

        cost = usage.get("cost_usd", 0.0)
        session.add(
            UsageRecord(
                id=f"usage_{uuid4().hex}",
                goal_id=run.goal_id,
                task_id=execution.step_id,
                run_id=f"{mapping.kanban_board}:{mapping.expected_run_id}",
                agent_id=execution.agent_id or "unknown",
                model=str(usage["model"]) if usage.get("model") else None,
                input_tokens=integer("input_tokens"),
                output_tokens=integer("output_tokens"),
                cost_usd=float(cost) if isinstance(cost, int | float) else 0.0,
                raw_json=usage,
                created_at=datetime.now(UTC),
            )
        )

    def _publish_handoffs(
        self,
        session: Session,
        *,
        run: HarnessRunRecord,
        from_task_id: str,
        summary: str,
        artifact_refs: tuple[str, ...],
    ) -> None:
        version = session.get(HarnessVersionRecord, run.harness_version_id)
        if version is None:
            raise RuntimeExecutionError("run Harness Version is missing")
        harness = ProgressiveHarness.model_validate(version.logical_ir_json)
        children = [
            physical.id
            for physical in compile_harness(harness).steps
            if from_task_id in physical.depends_on
        ]
        for child_id in children:
            existing = session.scalar(
                select(HandoffRecord).where(
                    HandoffRecord.goal_id == run.goal_id,
                    HandoffRecord.from_task_id == from_task_id,
                    HandoffRecord.to_task_id == child_id,
                )
            )
            if existing is not None:
                continue
            handoff = Handoff(
                summary=summary,
                artifact_refs=artifact_refs,
                confidence=1.0,
            )
            session.add(
                HandoffRecord(
                    id=f"handoff_{uuid4().hex}",
                    goal_id=run.goal_id,
                    from_task_id=from_task_id,
                    to_task_id=child_id,
                    payload_json=handoff.model_dump(mode="json"),
                    created_at=datetime.now(UTC),
                )
            )

    def _execute_gate(
        self,
        session: Session,
        run: HarnessRunRecord,
        goal: GoalRecord,
        step: RuntimeGateStep,
        execution: StepExecutionRecord,
        mapping: TaskMappingRecord,
    ) -> None:
        claimed = self._kanban.claim_task(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            claimer=f"agenthub:{run.id}:{step.id}",
            ttl_seconds=900,
        )
        if claimed is None or claimed.current_run_id is None:
            return
        mapping.expected_run_id = claimed.current_run_id
        execution.status = "running"
        execution.started_at = datetime.now(UTC)
        session.commit()
        workspace = Path(claimed.workspace_path or goal.project_root)
        result = self._gate_runner.run(step.checks, workspace=workspace)
        artifact = self._artifacts.publish(
            session,
            provenance=ArtifactProvenance(
                goal_id=goal.id,
                task_id=step.id,
                run_id=f"{mapping.kanban_board}:{claimed.current_run_id}",
                created_by_agent="agenthub://runtime",
            ),
            kind="test-log",
            media_type="text/plain",
            content=result.log(),
            metadata={"passed": result.passed},
        )
        _append_event(
            session,
            goal_id=goal.id,
            event_type="artifact.published",
            actor="agenthub://runtime",
            payload={"step_id": step.id, "artifact_id": artifact.id, "kind": artifact.kind},
            correlation_id=run.id,
        )
        if result.passed:
            self._kanban.complete(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                expected_run_id=claimed.current_run_id,
                summary="Runtime gate passed",
                metadata={"artifacts": [artifact.uri]},
            )
            execution.status = "succeeded"
            execution.ended_at = datetime.now(UTC)
            execution.result_json = {"passed": True, "artifact_id": artifact.id}
            _append_event(
                session,
                goal_id=goal.id,
                event_type="gate.completed",
                actor="agenthub://runtime",
                payload={"step_id": step.id, "passed": True, "artifact_id": artifact.id},
                correlation_id=run.id,
            )
            session.commit()
        else:
            self._kanban.block(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                expected_run_id=claimed.current_run_id,
                reason="runtime-gate-failed",
            )
            self._fail_run(session, run, goal, execution, "Runtime gate failed")

    @staticmethod
    def _parse_review_decision(artifacts: tuple[ProducedArtifact, ...]) -> str:
        reports = [artifact for artifact in artifacts if artifact.kind == "review_report"]
        if not reports:
            raise RuntimeExecutionError("review Worker did not produce review_report")
        for report in reports:
            text = report.content.decode(errors="replace").strip()
            candidates = [text, *reversed(text.splitlines())]
            for candidate in candidates:
                try:
                    payload = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                decision = payload.get("decision")
                findings = payload.get("findings")
                if decision in {"pass", "changes_required"} and isinstance(findings, list):
                    return decision
        raise RuntimeExecutionError("review_report does not satisfy ReviewResult contract")

    @staticmethod
    def _execution_for_step(
        session: Session, run_id: str, step_id: str
    ) -> StepExecutionRecord | None:
        return session.scalar(
            select(StepExecutionRecord).where(
                StepExecutionRecord.harness_run_id == run_id,
                StepExecutionRecord.step_id == step_id,
                StepExecutionRecord.attempt == 1,
            )
        )

    def _should_skip_loop_step(
        self, session: Session, run: HarnessRunRecord, physical: PhysicalStep
    ) -> bool:
        parent = self._execution_for_step(session, run.id, physical.depends_on[0])
        if parent is None:
            raise RuntimeExecutionError(f"loop step {physical.id} parent execution is missing")
        if physical.loop_phase == "repair":
            return (
                parent.result_json.get("review_decision") == "pass"
                or parent.result_json.get("skipped") is True
            )
        return parent.result_json.get("skipped") is True

    def _skip_step(
        self,
        session: Session,
        run: HarnessRunRecord,
        goal: GoalRecord,
        execution: StepExecutionRecord,
        mapping: TaskMappingRecord,
    ) -> None:
        claimed = self._kanban.claim_task(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            claimer=f"agenthub:{run.id}:{execution.step_id}",
            ttl_seconds=300,
        )
        if claimed is None or claimed.current_run_id is None:
            return
        mapping.expected_run_id = claimed.current_run_id
        if not self._kanban.complete(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            expected_run_id=claimed.current_run_id,
            summary="Loop iteration not required",
            metadata={"skipped": True},
        ):
            self._fail_run(session, run, goal, execution, "stale loop skip rejected")
            return
        now = datetime.now(UTC)
        execution.status = "succeeded"
        execution.started_at = now
        execution.ended_at = now
        execution.result_json = {"skipped": True}
        _append_event(
            session,
            goal_id=goal.id,
            event_type="step.skipped",
            actor="agenthub://runtime",
            payload={"step_id": execution.step_id, "reason": "review_passed"},
            correlation_id=run.id,
        )
        session.commit()

    def _complete_loop(
        self,
        session: Session,
        run: HarnessRunRecord,
        goal: GoalRecord,
        step: LoopStep,
        execution: StepExecutionRecord,
        mapping: TaskMappingRecord,
    ) -> None:
        review_ids = [*step.depends_on]
        review_ids.extend(
            f"{step.id}_review_{iteration}"
            for iteration in range(1, step.max_iterations + 1)
        )
        decisions = [
            candidate.result_json.get("review_decision")
            for review_id in review_ids
            if (candidate := self._execution_for_step(session, run.id, review_id)) is not None
            and candidate.result_json.get("skipped") is not True
        ]
        if not decisions or decisions[-1] != "pass":
            self._fail_run(
                session,
                run,
                goal,
                execution,
                f"Review repair limit exhausted after {step.max_iterations} rounds",
            )
            return
        claimed = self._kanban.claim_task(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            claimer=f"agenthub:{run.id}:{step.id}",
            ttl_seconds=300,
        )
        if claimed is None or claimed.current_run_id is None:
            return
        mapping.expected_run_id = claimed.current_run_id
        if not self._kanban.complete(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            expected_run_id=claimed.current_run_id,
            summary="Bounded Review repair policy satisfied",
            metadata={"rounds": len(decisions) - 1},
        ):
            self._fail_run(session, run, goal, execution, "stale loop completion rejected")
            return
        now = datetime.now(UTC)
        execution.status = "succeeded"
        execution.started_at = now
        execution.ended_at = now
        execution.result_json = {
            "review_decision": "pass",
            "repair_rounds": len(decisions) - 1,
        }
        _append_event(
            session,
            goal_id=goal.id,
            event_type="loop.completed",
            actor="agenthub://runtime",
            payload={"step_id": step.id, "repair_rounds": len(decisions) - 1},
            correlation_id=run.id,
        )
        session.commit()

    def _complete_parallel(
        self,
        session: Session,
        run: HarnessRunRecord,
        goal: GoalRecord,
        step: ParallelStep,
        execution: StepExecutionRecord,
        mapping: TaskMappingRecord,
    ) -> None:
        claimed = self._kanban.claim_task(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            claimer=f"agenthub:{run.id}:{step.id}",
            ttl_seconds=300,
        )
        if claimed is None or claimed.current_run_id is None:
            return
        mapping.expected_run_id = claimed.current_run_id
        if not self._kanban.complete(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            expected_run_id=claimed.current_run_id,
            summary="Parallel branches completed",
            metadata={"branches": [branch.id for branch in step.branches]},
        ):
            self._fail_run(session, run, goal, execution, "stale parallel completion rejected")
            return
        now = datetime.now(UTC)
        execution.status = "succeeded"
        execution.started_at = now
        execution.ended_at = now
        execution.result_json = {"branches": [branch.id for branch in step.branches]}
        _append_event(
            session,
            goal_id=goal.id,
            event_type="parallel.completed",
            actor="agenthub://runtime",
            payload={"step_id": step.id, "branches": [branch.id for branch in step.branches]},
            correlation_id=run.id,
        )
        session.commit()

    def _wait_for_approval(
        self,
        session: Session,
        run: HarnessRunRecord,
        goal: GoalRecord,
        step: WaitApprovalStep,
        execution: StepExecutionRecord,
        mapping: TaskMappingRecord,
    ) -> None:
        approval = next(
            (
                candidate
                for candidate in session.scalars(
                    select(ApprovalRecord).where(
                        ApprovalRecord.goal_id == goal.id,
                        ApprovalRecord.type == step.approval_type,
                    )
                )
                if candidate.request_json.get("step_id") == step.id
            ),
            None,
        )
        if approval is not None and approval.status == "approved":
            claimed = self._kanban.claim_task(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                claimer=f"agenthub:{run.id}:{step.id}",
                ttl_seconds=300,
            )
            if claimed is None or claimed.current_run_id is None:
                return
            mapping.expected_run_id = claimed.current_run_id
            if not self._kanban.complete(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                expected_run_id=claimed.current_run_id,
                summary="Approval granted",
                metadata={"approval_id": approval.id},
            ):
                self._fail_run(
                    session, run, goal, execution, "stale Approval completion rejected"
                )
                return
            now = datetime.now(UTC)
            execution.status = "succeeded"
            execution.started_at = execution.started_at or now
            execution.ended_at = now
            execution.result_json = {"approval_id": approval.id, "approved": True}
            has_completed_review = session.scalar(
                select(StepExecutionRecord.id).where(
                    StepExecutionRecord.harness_run_id == run.id,
                    StepExecutionRecord.kind == "review",
                    StepExecutionRecord.status == "succeeded",
                )
            )
            domain_goal = goal_to_domain(goal)
            if has_completed_review and domain_goal.status is GoalStatus.RUNNING:
                domain_goal = domain_goal.transition_to(GoalStatus.REVIEW, actor="runtime")
                goal.status = domain_goal.status
                goal.updated_at = domain_goal.updated_at
            _append_event(
                session,
                goal_id=goal.id,
                event_type="approval.consumed",
                actor="agenthub://runtime",
                payload={"approval_id": approval.id, "step_id": step.id},
                correlation_id=run.id,
            )
            session.commit()
            return
        if approval is not None and approval.status == "rejected":
            self._fail_run(session, run, goal, execution, "Required Approval was rejected")
            return
        if approval is None:
            claimed = self._kanban.claim_task(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                claimer=f"agenthub:{run.id}:{step.id}",
                ttl_seconds=300,
            )
            if claimed is None or claimed.current_run_id is None:
                return
            mapping.expected_run_id = claimed.current_run_id
            approval = ApprovalRecord(
                id=f"approval_{uuid4().hex}",
                goal_id=goal.id,
                type=step.approval_type,
                status="pending",
                request_json={
                    "step_id": step.id,
                    "harness_run_id": run.id,
                    "prompt": step.prompt,
                },
                decision_json={},
                created_at=datetime.now(UTC),
                resolved_at=None,
            )
            session.add(approval)
            if not self._kanban.block(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                expected_run_id=claimed.current_run_id,
                reason=f"approval-required:{approval.id}",
            ):
                self._fail_run(session, run, goal, execution, "stale Approval wait rejected")
                return
        execution.status = "waiting"
        execution.started_at = execution.started_at or datetime.now(UTC)
        execution.result_json = {"approval_id": approval.id}
        run.status = "waiting"
        run.current_phase = step.id
        domain_goal = goal_to_domain(goal)
        if domain_goal.status in {GoalStatus.RUNNING, GoalStatus.REVIEW}:
            domain_goal = domain_goal.transition_to(GoalStatus.WAITING, actor="runtime")
            goal.status = domain_goal.status
            goal.updated_at = domain_goal.updated_at
        _append_event(
            session,
            goal_id=goal.id,
            event_type="approval.requested",
            actor="agenthub://runtime",
            payload={"approval_id": approval.id, "type": approval.type, "step_id": step.id},
            correlation_id=run.id,
        )
        session.commit()

    def resume_approval(self, goal_id: str, approval_id: str) -> None:
        with self._session_factory() as session:
            approval = session.get(ApprovalRecord, approval_id)
            if approval is None or approval.goal_id != goal_id:
                raise RuntimeExecutionError("approval not found")
            step_id = approval.request_json.get("step_id")
            run_id = approval.request_json.get("harness_run_id")
            if not isinstance(step_id, str) or not isinstance(run_id, str):
                return
            run = session.get(HarnessRunRecord, run_id)
            goal = session.get(GoalRecord, goal_id)
            execution = self._execution_for_step(session, run_id, step_id)
            mapping = session.scalar(
                select(TaskMappingRecord).where(
                    TaskMappingRecord.harness_run_id == run_id,
                    TaskMappingRecord.step_id == step_id,
                )
            )
            if run is None or goal is None or execution is None or mapping is None:
                raise RuntimeExecutionError("approval continuation is missing Runtime state")
            if execution.status != "waiting":
                return
            if approval.status == "rejected":
                self._fail_run(session, run, goal, execution, "Required Approval was rejected")
                return
            if approval.status != "approved":
                return
            if not self._kanban.unblock(
                board=mapping.kanban_board, task_id=mapping.kanban_task_id
            ):
                task = self._kanban.get_task(
                    board=mapping.kanban_board, task_id=mapping.kanban_task_id
                )
                if task is None or task.status != "ready":
                    raise RuntimeExecutionError("Approval task could not be resumed")
            execution.status = "pending"
            run.status = "running"
            run.current_phase = None
            domain_goal = goal_to_domain(goal)
            if domain_goal.status is GoalStatus.WAITING:
                domain_goal = domain_goal.transition_to(GoalStatus.RUNNING, actor="runtime")
                goal.status = domain_goal.status
                goal.updated_at = domain_goal.updated_at
            _append_event(
                session,
                goal_id=goal.id,
                event_type="approval.resumed",
                actor="agenthub://runtime",
                payload={"approval_id": approval.id, "step_id": step_id},
                correlation_id=run.id,
            )
            session.commit()

    def _finalize(
        self,
        session: Session,
        run: HarnessRunRecord,
        goal: GoalRecord,
        step: FinalizeStep,
        execution: StepExecutionRecord,
        mapping: TaskMappingRecord,
    ) -> None:
        executions = session.scalars(
            select(StepExecutionRecord).where(StepExecutionRecord.harness_run_id == run.id)
        ).all()
        if any(item.status != "succeeded" for item in executions if item.step_id != step.id):
            return
        artifact_kinds = set(
            session.scalars(
                select(ArtifactRecord.kind).where(ArtifactRecord.goal_id == goal.id)
            )
        )
        delivery_kind = "candidate_commit" if step.delivery == "candidate_commit" else "patch"
        required = {delivery_kind, "test-log", "review_report"}
        missing = required - artifact_kinds
        implementers = {
            item.agent_id for item in executions if item.kind == "agent_call" and item.agent_id
        }
        reviewers = {
            item.agent_id for item in executions if item.kind == "review" and item.agent_id
        }
        if missing or not reviewers or implementers & reviewers:
            independent = not bool(implementers & reviewers)
            reason = (
                f"completion gate failed; missing={sorted(missing)}, "
                f"independent={independent}"
            )
            self._fail_run(session, run, goal, execution, reason)
            return
        claimed = self._kanban.claim_task(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            claimer=f"agenthub:{run.id}:{step.id}",
            ttl_seconds=300,
        )
        if claimed is None or claimed.current_run_id is None:
            return
        mapping.expected_run_id = claimed.current_run_id
        if not self._kanban.complete(
            board=mapping.kanban_board,
            task_id=mapping.kanban_task_id,
            expected_run_id=claimed.current_run_id,
            summary="Completion policy satisfied",
            metadata={"artifact_kinds": sorted(artifact_kinds)},
        ):
            self._fail_run(session, run, goal, execution, "stale finalize completion rejected")
            return
        now = datetime.now(UTC)
        execution.status = "succeeded"
        execution.started_at = now
        execution.ended_at = now
        execution.result_json = {"completion_policy": "passed"}
        run.status = "completed"
        run.current_phase = "finalize"
        run.ended_at = now
        domain_goal = goal_to_domain(goal).transition_to(
            GoalStatus.COMPLETED, actor="completion_controller"
        )
        goal.status = domain_goal.status
        goal.updated_at = domain_goal.updated_at
        _append_event(
            session,
            goal_id=goal.id,
            event_type="goal.completed",
            actor="agenthub://completion-controller",
            payload={"harness_run_id": run.id},
            correlation_id=run.id,
        )
        if step.delivery == "candidate_commit":
            approval = session.scalar(
                select(ApprovalRecord).where(
                    ApprovalRecord.goal_id == goal.id,
                    ApprovalRecord.type == "merge",
                )
            )
            if approval is None:
                approval = ApprovalRecord(
                    id=f"approval_{uuid4().hex}",
                    goal_id=goal.id,
                    type="merge",
                    status="pending",
                    request_json={"delivery": "candidate_commit"},
                    decision_json={},
                    created_at=now,
                    resolved_at=None,
                )
                session.add(approval)
                _append_event(
                    session,
                    goal_id=goal.id,
                    event_type="approval.requested",
                    actor="agenthub://completion-controller",
                    payload={"approval_id": approval.id, "type": "merge"},
                    correlation_id=run.id,
                )
        session.commit()

    def _fail_run(
        self,
        session: Session,
        run: HarnessRunRecord,
        goal: GoalRecord,
        execution: StepExecutionRecord,
        reason: str,
    ) -> None:
        now = datetime.now(UTC)
        execution.status = "failed"
        execution.ended_at = now
        execution.result_json = {"failure": reason}
        run.status = "failed"
        run.ended_at = now
        domain_goal = goal_to_domain(goal)
        if domain_goal.status in {GoalStatus.RUNNING, GoalStatus.REVIEW, GoalStatus.WAITING}:
            domain_goal = domain_goal.transition_to(GoalStatus.FAILED, actor="runtime")
            goal.status = domain_goal.status
            goal.updated_at = domain_goal.updated_at
        _append_event(
            session,
            goal_id=goal.id,
            event_type="goal.failed",
            actor="agenthub://runtime",
            payload={"step_id": execution.step_id, "reason": reason},
            correlation_id=run.id,
        )
        session.commit()

    @staticmethod
    def _fake_agent_id(step: object) -> str:
        if isinstance(step, ReviewStep):
            return "fake://reviewer"
        if isinstance(step, AgentCallStep):
            return "fake://default"
        return "agenthub://runtime"

    def _binding_for_step(
        self, session: Session, run: HarnessRunRecord, step: object
    ) -> AgentDefinition | None:
        if not isinstance(step, (AgentCallStep, ReviewStep)):
            return None
        selector = step.selector
        if self._default_worker_lane == "fake" and selector.agent_id is None:
            return None
        if self._registry is None:
            raise RuntimeExecutionError("Agent Registry is unavailable")
        if selector.prefer_binding_from is not None:
            preferred_execution = self._execution_for_step(
                session, run.id, selector.prefer_binding_from
            )
            preferred_id = preferred_execution.agent_id if preferred_execution else None
            if preferred_id is None or preferred_id.startswith("fake://"):
                return None
            preferred = next(
                (agent for agent in self._registry.agents if agent.id == preferred_id), None
            )
            if preferred is None:
                raise RuntimeExecutionError(
                    f"preferred Agent binding {preferred_id} is unavailable"
                )
            return preferred
        excluded_ids: set[str] = set()
        for excluded_step in selector.exclude_agents_from:
            execution = session.scalar(
                select(StepExecutionRecord).where(
                    StepExecutionRecord.harness_run_id == run.id,
                    StepExecutionRecord.step_id == excluded_step,
                    StepExecutionRecord.attempt == 1,
                )
            )
            if execution and execution.agent_id:
                excluded_ids.add(execution.agent_id)
        requested = selector.agent_id
        if requested is None and isinstance(step, AgentCallStep):
            requested = next(
                (
                    agent.id
                    for agent in self._registry.agents
                    if agent.runtime == self._default_worker_lane
                ),
                None,
            )
        return resolve_agent(
            self._registry,
            AgentDemand(
                capabilities=frozenset(selector.capabilities),
                repository_write=(
                    isinstance(step, AgentCallStep)
                    and step.workspace.mode == "write_candidate"
                ),
                excluded_agent_ids=frozenset(excluded_ids),
                requested_agent_id=requested,
            ),
            available_runtimes=self._available_runtimes,
        )

    @staticmethod
    def _assignee(binding: AgentDefinition | None, step: object) -> str:
        if binding is None:
            return "fake:reviewer" if isinstance(step, ReviewStep) else "fake:default"
        if binding.runtime == "hermes":
            assert binding.profile is not None
            return binding.profile
        return binding.id.replace("://", ":", 1)

    @staticmethod
    def _outputs(step: object) -> tuple[str, ...]:
        if isinstance(step, (AgentCallStep, ReviewStep)):
            return step.outputs
        if isinstance(step, RuntimeGateStep):
            return ("test-log",)
        if isinstance(step, FinalizeStep):
            return ("goal_summary",)
        return ()

    @staticmethod
    def _objective(step: object) -> str:
        if isinstance(step, AgentCallStep):
            return step.task
        if isinstance(step, ReviewStep):
            return "Independently review the candidate result and evidence"
        if isinstance(step, RuntimeGateStep):
            return "Execute deterministic Runtime Gate checks"
        if isinstance(step, FinalizeStep):
            return "Apply the Runtime Completion Policy"
        return "Wait for Runtime action"

    def _task_envelope(
        self,
        session: Session,
        goal: GoalRecord,
        run: HarnessRunRecord,
        step: AgentCallStep | ReviewStep,
        workspace_path: Path,
    ) -> dict[str, object]:
        handoffs = session.scalars(
            select(HandoffRecord).where(
                HandoffRecord.goal_id == goal.id,
                HandoffRecord.to_task_id == step.id,
            )
        ).all()
        handoff_refs = tuple(f"handoff://{handoff.id}" for handoff in handoffs)
        artifact_refs = tuple(
            dict.fromkeys(
                str(ref)
                for handoff in handoffs
                for ref in handoff.payload_json.get("artifact_refs", [])
            )
        )
        if isinstance(step, ReviewStep):
            requested_kinds = set(step.inputs)
            if "checks" in requested_kinds:
                requested_kinds.add("test-log")
            related = session.scalars(
                select(ArtifactRecord).where(
                    ArtifactRecord.goal_id == goal.id,
                    ArtifactRecord.kind.in_(requested_kinds),
                )
            ).all()
            artifact_refs = tuple(
                dict.fromkeys((*artifact_refs, *(artifact.uri for artifact in related)))
            )
        envelope = project_task_envelope(
            goal=goal_to_domain(goal),
            run_id=run.id,
            step=step,
            workspace_path=workspace_path,
            handoff_refs=handoff_refs,
            artifact_refs=artifact_refs,
        )
        return envelope.model_dump(mode="json", by_alias=True)
