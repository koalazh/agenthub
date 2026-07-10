import json
import shutil
from pathlib import Path
from typing import Any

from agenthub.workers.base import (
    AgentRuntimeDescriptor,
    WorkerEvent,
    WorkerEventType,
    WorkerStartRequest,
)
from agenthub.workers.process_adapter import CommandBuilder, JsonlProcessWorkerAdapter


def _codex_event(payload: dict[str, Any]) -> WorkerEvent | None:
    event_type = payload.get("type")
    if event_type == "turn.started":
        return WorkerEvent(type=WorkerEventType.PROGRESS, payload={"phase": "turn"})
    if event_type == "item.started":
        return WorkerEvent(type=WorkerEventType.TOOL_STARTED, payload=payload)
    if event_type == "item.completed":
        return WorkerEvent(type=WorkerEventType.TOOL_COMPLETED, payload=payload)
    if event_type == "turn.completed":
        return WorkerEvent(type=WorkerEventType.PROGRESS, payload={"phase": "turn_completed"})
    if event_type in {"error", "turn.failed"}:
        return WorkerEvent(type=WorkerEventType.FAILED, payload=payload)
    return None


class CodexWorkerAdapter(JsonlProcessWorkerAdapter):
    def __init__(self, *, command_builder: CommandBuilder | None = None) -> None:
        executable = shutil.which("codex")
        if command_builder is None and executable is None:
            raise RuntimeError("Codex CLI is not installed")

        def default_command(request: WorkerStartRequest, final_output: Path) -> list[str]:
            sandbox = (
                "workspace-write"
                if request.task_envelope["constraints"]["permissions"]["repository"]
                == "write_candidate"
                else "read-only"
            )
            prompt = json.dumps(request.task_envelope, ensure_ascii=False)
            return [
                executable or "codex",
                "exec",
                "--json",
                "--sandbox",
                sandbox,
                "-C",
                str(request.workspace_path),
                "-o",
                str(final_output),
                prompt,
            ]

        super().__init__(
            descriptor=AgentRuntimeDescriptor(
                id="codex://default",
                runtime="codex",
                capabilities=("code-implementation", "debugging", "code-review"),
                max_parallel_runs=1,
            ),
            command_builder=command_builder or default_command,
            event_mapper=_codex_event,
        )
