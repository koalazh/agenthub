from collections.abc import AsyncIterator
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class WorkerEventType(StrEnum):
    ACCEPTED = "accepted"
    STARTED = "started"
    PROGRESS = "progress"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    ARTIFACT_CREATED = "artifact_created"
    INPUT_REQUIRED = "input_required"
    APPROVAL_REQUIRED = "approval_required"
    HEARTBEAT = "heartbeat"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class WorkerResultStatus(StrEnum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELED = "canceled"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AgentRuntimeDescriptor(FrozenModel):
    id: str
    runtime: str
    capabilities: tuple[str, ...]
    max_parallel_runs: int = Field(ge=1)


class WorkerStartRequest(FrozenModel):
    goal_id: str
    task_id: str
    kanban_task_id: str
    expected_run_id: int
    agent_id: str
    task_envelope: dict[str, Any]
    workspace_path: Path
    timeout_seconds: int = Field(ge=1)
    environment: dict[str, str] = {}
    artifact_output_dir: Path


class WorkerHandle(FrozenModel):
    id: str
    adapter_id: str


class WorkerEvent(FrozenModel):
    type: WorkerEventType
    payload: dict[str, Any] = {}


class ProducedArtifact(FrozenModel):
    kind: str
    filename: str
    media_type: str = "text/plain"
    content: bytes


class WorkerFailure(FrozenModel):
    type: str
    message: str


class WorkerResult(FrozenModel):
    status: WorkerResultStatus
    summary: str
    artifacts: tuple[ProducedArtifact, ...] = ()
    changed_files: tuple[str, ...] = ()
    commit_sha: str | None = None
    tests_run: tuple[str, ...] = ()
    usage: dict[str, Any] = {}
    session_ref: str | None = None
    failure: WorkerFailure | None = None


class WorkerAdapter(Protocol):
    async def describe(self) -> AgentRuntimeDescriptor: ...

    async def start(self, request: WorkerStartRequest) -> WorkerHandle: ...

    async def stream_events(self, handle: WorkerHandle) -> AsyncIterator[WorkerEvent]: ...

    async def send_input(self, handle: WorkerHandle, payload: dict[str, Any]) -> None: ...

    async def cancel(self, handle: WorkerHandle) -> None: ...

    async def collect_result(self, handle: WorkerHandle) -> WorkerResult: ...
