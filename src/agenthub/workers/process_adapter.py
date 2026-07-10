import asyncio
import json
import os
import signal
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

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

CommandBuilder = Callable[[WorkerStartRequest, Path], list[str]]
EventMapper = Callable[[dict[str, Any]], WorkerEvent | None]


@dataclass
class _ProcessRun:
    request: WorkerStartRequest
    process: asyncio.subprocess.Process
    final_output: Path
    stderr_task: asyncio.Task[bytes]
    output_lines: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    session_ref: str | None = None
    terminal_emitted: bool = False
    failed_event: bool = False


class JsonlProcessWorkerAdapter:
    def __init__(
        self,
        *,
        descriptor: AgentRuntimeDescriptor,
        command_builder: CommandBuilder,
        event_mapper: EventMapper,
    ) -> None:
        self._descriptor = descriptor
        self._command_builder = command_builder
        self._event_mapper = event_mapper
        self._runs: dict[str, _ProcessRun] = {}

    async def describe(self) -> AgentRuntimeDescriptor:
        return self._descriptor

    async def start(self, request: WorkerStartRequest) -> WorkerHandle:
        request.artifact_output_dir.mkdir(parents=True, exist_ok=True)
        final_output = request.artifact_output_dir / "worker-final.txt"
        command = self._command_builder(request, final_output)
        environment = dict(os.environ)
        environment.update(request.environment)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=request.workspace_path,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stderr is not None
        handle = WorkerHandle(id=f"proc_{uuid4().hex}", adapter_id=self._descriptor.id)
        self._runs[handle.id] = _ProcessRun(
            request=request,
            process=process,
            final_output=final_output,
            stderr_task=asyncio.create_task(process.stderr.read()),
        )
        return handle

    async def stream_events(self, handle: WorkerHandle) -> AsyncIterator[WorkerEvent]:
        run = self._run(handle)
        yield WorkerEvent(type=WorkerEventType.ACCEPTED)
        yield WorkerEvent(type=WorkerEventType.STARTED, payload={"pid": run.process.pid})
        assert run.process.stdout is not None
        while line_bytes := await run.process.stdout.readline():
            line = line_bytes.decode(errors="replace").rstrip()
            if not line:
                continue
            run.output_lines.append(line)
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                yield WorkerEvent(type=WorkerEventType.PROGRESS, payload={"message": line})
                continue
            if isinstance(payload.get("usage"), dict):
                run.usage.update(payload["usage"])
            session_ref = payload.get("thread_id") or payload.get("session_id")
            if session_ref:
                run.session_ref = str(session_ref)
            event = self._event_mapper(payload)
            if event is not None:
                if event.type in {
                    WorkerEventType.COMPLETED,
                    WorkerEventType.FAILED,
                    WorkerEventType.CANCELED,
                }:
                    run.terminal_emitted = True
                if event.type is WorkerEventType.FAILED:
                    run.failed_event = True
                yield event
        returncode = await run.process.wait()
        if not run.terminal_emitted:
            if returncode == 0 and not run.failed_event:
                terminal = WorkerEventType.COMPLETED
            elif returncode < 0:
                terminal = WorkerEventType.CANCELED
            else:
                terminal = WorkerEventType.FAILED
            run.terminal_emitted = True
            yield WorkerEvent(type=terminal, payload={"returncode": returncode})

    async def send_input(self, handle: WorkerHandle, payload: dict[str, Any]) -> None:
        self._run(handle)
        raise RuntimeError("non-interactive CLI lane does not accept mid-run input")

    async def cancel(self, handle: WorkerHandle) -> None:
        run = self._run(handle)
        if run.process.returncode is not None:
            return
        try:
            os.killpg(run.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(run.process.wait(), timeout=5)
        except TimeoutError:
            os.killpg(run.process.pid, signal.SIGKILL)
            await run.process.wait()

    async def collect_result(self, handle: WorkerHandle) -> WorkerResult:
        run = self._run(handle)
        if run.process.returncode is None:
            raise RuntimeError("Worker process is still running")
        stderr = (await run.stderr_task).decode(errors="replace")
        if run.final_output.is_file():
            content = run.final_output.read_bytes()
        else:
            content = ("\n".join(run.output_lines) + "\n" + stderr).encode()
        if run.process.returncode == 0 and not run.failed_event:
            status = WorkerResultStatus.COMPLETED
            summary = f"{self._descriptor.runtime} CLI completed"
            failure = None
        elif run.process.returncode < 0:
            status = WorkerResultStatus.CANCELED
            summary = f"{self._descriptor.runtime} CLI canceled"
            failure = None
        else:
            status = WorkerResultStatus.FAILED
            summary = f"{self._descriptor.runtime} CLI failed with {run.process.returncode}"
            from agenthub.workers.base import WorkerFailure

            failure = WorkerFailure(type="PERMANENT_FAILURE", message=stderr or summary)
        requested_artifacts = run.request.task_envelope.get("output_contract", {}).get(
            "artifacts", []
        )
        artifact_kinds = tuple(str(kind) for kind in requested_artifacts) or ("worker-result",)
        artifacts = tuple(
            ProducedArtifact(
                kind=kind,
                filename=f"{kind}.txt",
                media_type="text/plain",
                content=content,
            )
            for kind in artifact_kinds
        )
        return WorkerResult(
            status=status,
            summary=summary,
            artifacts=artifacts,
            usage=run.usage,
            session_ref=run.session_ref,
            failure=failure,
        )

    def _run(self, handle: WorkerHandle) -> _ProcessRun:
        try:
            return self._runs[handle.id]
        except KeyError as exc:
            raise LookupError(f"unknown process Worker handle {handle.id}") from exc
