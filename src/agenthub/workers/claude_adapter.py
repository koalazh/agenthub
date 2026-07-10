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


def _claude_event(payload: dict[str, Any]) -> WorkerEvent | None:
    event_type = payload.get("type")
    if event_type == "assistant":
        return WorkerEvent(type=WorkerEventType.PROGRESS, payload={"phase": "assistant"})
    if event_type in {"tool_use", "tool_started"}:
        return WorkerEvent(type=WorkerEventType.TOOL_STARTED, payload=payload)
    if event_type in {"tool_result", "tool_completed"}:
        return WorkerEvent(type=WorkerEventType.TOOL_COMPLETED, payload=payload)
    if event_type == "result" and payload.get("is_error"):
        return WorkerEvent(type=WorkerEventType.FAILED, payload=payload)
    if event_type == "result":
        return WorkerEvent(type=WorkerEventType.PROGRESS, payload={"phase": "result"})
    return None


class ClaudeWorkerAdapter(JsonlProcessWorkerAdapter):
    def __init__(self, *, command_builder: CommandBuilder | None = None) -> None:
        executable = shutil.which("claude")
        if command_builder is None and executable is None:
            raise RuntimeError("Claude CLI is not installed")

        def default_command(request: WorkerStartRequest, _: Path) -> list[str]:
            permission = (
                "acceptEdits"
                if request.task_envelope["constraints"]["permissions"]["repository"]
                == "write_candidate"
                else "plan"
            )
            return [
                executable or "claude",
                "--print",
                "--verbose",
                "--output-format",
                "stream-json",
                "--permission-mode",
                permission,
                "--no-session-persistence",
                json.dumps(request.task_envelope, ensure_ascii=False),
            ]

        super().__init__(
            descriptor=AgentRuntimeDescriptor(
                id="claude://default",
                runtime="claude",
                capabilities=("code-analysis", "code-implementation", "code-review"),
                max_parallel_runs=1,
            ),
            command_builder=command_builder or default_command,
            event_mapper=_claude_event,
        )
