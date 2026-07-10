import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agenthub.hermes.kanban_adapter import HermesKanbanAdapter
from agenthub.workers.base import (
    AgentRuntimeDescriptor,
    ProducedArtifact,
    WorkerEvent,
    WorkerEventType,
    WorkerHandle,
    WorkerResult,
    WorkerResultStatus,
    WorkerStartRequest,
)

_EVENT_MAP = {
    "claimed": WorkerEventType.STARTED,
    "heartbeat": WorkerEventType.HEARTBEAT,
    "commented": WorkerEventType.PROGRESS,
    "completed": WorkerEventType.COMPLETED,
    "blocked": WorkerEventType.INPUT_REQUIRED,
    "crashed": WorkerEventType.FAILED,
    "gave_up": WorkerEventType.FAILED,
    "timed_out": WorkerEventType.FAILED,
    "archived": WorkerEventType.CANCELED,
}


@dataclass
class _HermesRun:
    request: WorkerStartRequest
    board: str
    event_cursor: int
    accepted_emitted: bool = False


class HermesProfileWorkerAdapter:
    def __init__(
        self,
        *,
        kanban: HermesKanbanAdapter,
        board: str,
        agent_id: str,
        profile: str,
        spawn_fn: Callable[..., int | None] | None = None,
    ) -> None:
        self._kanban = kanban
        self._board = board
        self._agent_id = agent_id
        self._profile = profile
        self._spawn_fn = spawn_fn
        self._runs: dict[str, _HermesRun] = {}

    async def describe(self) -> AgentRuntimeDescriptor:
        return AgentRuntimeDescriptor(
            id=self._agent_id,
            runtime="hermes",
            capabilities=("code-analysis", "code-implementation", "code-review"),
            max_parallel_runs=1,
        )

    async def start(self, request: WorkerStartRequest) -> WorkerHandle:
        task = self._kanban.get_task(board=self._board, task_id=request.kanban_task_id)
        if task is None:
            raise LookupError(f"Hermes task {request.kanban_task_id} does not exist")
        if request.agent_id != self._agent_id:
            raise ValueError(f"request targets {request.agent_id!r}, expected {self._agent_id!r}")
        if task.assignee != self._profile:
            raise ValueError(
                f"Hermes task assignee {task.assignee!r} does not match {self._profile!r}"
            )
        existing_events = self._kanban.list_events(
            board=self._board, task_id=request.kanban_task_id
        )
        cursor = max((event.id for event in existing_events), default=0)
        self._kanban.dispatch_once(
            board=self._board,
            spawn_fn=self._spawn_fn,
            max_spawn=1,
            max_in_progress=1,
        )
        handle = WorkerHandle(id=f"hermes_{uuid4().hex}", adapter_id=request.agent_id)
        self._runs[handle.id] = _HermesRun(
            request=request, board=self._board, event_cursor=cursor
        )
        return handle

    async def stream_events(self, handle: WorkerHandle) -> AsyncIterator[WorkerEvent]:
        run = self._run(handle)
        if not run.accepted_emitted:
            run.accepted_emitted = True
            yield WorkerEvent(type=WorkerEventType.ACCEPTED)
        events = self._kanban.list_events(
            board=run.board, task_id=run.request.kanban_task_id
        )
        for event in events:
            if event.id <= run.event_cursor or event.kind not in _EVENT_MAP:
                continue
            run.event_cursor = event.id
            yield WorkerEvent(
                type=_EVENT_MAP[event.kind],
                payload={"hermes_event": event.kind, **(event.payload or {})},
            )

    async def send_input(self, handle: WorkerHandle, payload: dict[str, Any]) -> None:
        run = self._run(handle)
        body = str(payload.get("message", "")).strip()
        if not body:
            raise ValueError("Hermes Worker input requires a message")
        self._kanban.add_comment(
            board=run.board,
            task_id=run.request.kanban_task_id,
            author="agenthub-runtime",
            body=body,
        )

    async def cancel(self, handle: WorkerHandle) -> None:
        run = self._run(handle)
        self._kanban.archive(board=run.board, task_id=run.request.kanban_task_id)

    async def collect_result(self, handle: WorkerHandle) -> WorkerResult:
        run = self._run(handle)
        task = self._kanban.get_task(board=run.board, task_id=run.request.kanban_task_id)
        if task is None:
            raise LookupError(f"Hermes task {run.request.kanban_task_id} disappeared")
        status_map = {
            "done": WorkerResultStatus.COMPLETED,
            "blocked": WorkerResultStatus.BLOCKED,
            "archived": WorkerResultStatus.CANCELED,
        }
        if task.status not in status_map and task.status not in {
            "crashed",
            "gave_up",
            "timed_out",
        }:
            raise RuntimeError(f"Hermes task {task.id} is not terminal: {task.status}")
        status = status_map.get(task.status, WorkerResultStatus.FAILED)
        requested = tuple(
            str(kind)
            for kind in run.request.task_envelope.get("output_contract", {}).get(
                "artifacts", []
            )
        )
        terminal_event = next(
            (
                event
                for event in reversed(
                    self._kanban.list_events(
                        board=run.board, task_id=run.request.kanban_task_id
                    )
                )
                if event.kind in {"completed", "blocked", "crashed", "gave_up", "timed_out"}
            ),
            None,
        )
        payload = terminal_event.payload if terminal_event and terminal_event.payload else {}
        summary = str(payload.get("summary") or f"Hermes task {task.id} ended with {task.status}")
        artifacts: list[ProducedArtifact] = []
        for kind in requested:
            if kind == "review_report":
                try:
                    review = json.loads(summary)
                except json.JSONDecodeError:
                    review = {"decision": None, "findings": []}
                content = json.dumps(review).encode()
                media_type = "application/json"
                filename = "review_report.json"
            else:
                content = f"{summary}\n".encode()
                media_type = "text/plain"
                filename = f"{kind}.txt"
            artifacts.append(
                ProducedArtifact(
                    kind=kind,
                    filename=filename,
                    media_type=media_type,
                    content=content,
                )
            )
        return WorkerResult(
            status=status,
            summary=summary,
            artifacts=tuple(artifacts),
            session_ref=f"hermes-kanban://{run.board}/{task.id}",
        )

    def _run(self, handle: WorkerHandle) -> _HermesRun:
        try:
            return self._runs[handle.id]
        except KeyError as exc:
            raise LookupError(f"unknown Hermes Worker handle {handle.id}") from exc
