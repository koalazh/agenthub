import sys
from pathlib import Path

import pytest

from agenthub.workers.base import WorkerEventType, WorkerResultStatus, WorkerStartRequest
from agenthub.workers.claude_adapter import ClaudeWorkerAdapter
from agenthub.workers.codex_adapter import CodexWorkerAdapter
from agenthub.workers.supervisor import ExternalLaneSupervisor


def request(tmp_path: Path, agent_id: str = "codex://default") -> WorkerStartRequest:
    return WorkerStartRequest(
        goal_id="goal_test",
        task_id="implement",
        kanban_task_id="t_test",
        expected_run_id=1,
        agent_id=agent_id,
        task_envelope={
            "constraints": {"permissions": {"repository": "write_candidate"}},
            "output_contract": {"artifacts": ["candidate_commit"]},
        },
        workspace_path=tmp_path,
        timeout_seconds=60,
        artifact_output_dir=tmp_path / "artifacts" / agent_id.split(":")[0],
    )


def python_jsonl(script: str):
    return lambda _request, _output: [sys.executable, "-c", script]


@pytest.mark.asyncio
async def test_codex_jsonl_events_are_normalized(tmp_path: Path) -> None:
    script = (
        "import json; "
        "events=["
        "{'type':'thread.started','thread_id':'thread_1'},"
        "{'type':'turn.started'},"
        "{'type':'item.started','item':{'type':'command_execution'}},"
        "{'type':'item.completed','item':{'type':'command_execution'}},"
        "{'type':'turn.completed','usage':{'input_tokens':3,'output_tokens':2}}]; "
        "[print(json.dumps(e), flush=True) for e in events]"
    )
    adapter = CodexWorkerAdapter(command_builder=python_jsonl(script))
    handle = await adapter.start(request(tmp_path))
    events = [event async for event in adapter.stream_events(handle)]
    result = await adapter.collect_result(handle)

    assert [event.type for event in events] == [
        WorkerEventType.ACCEPTED,
        WorkerEventType.STARTED,
        WorkerEventType.PROGRESS,
        WorkerEventType.TOOL_STARTED,
        WorkerEventType.TOOL_COMPLETED,
        WorkerEventType.PROGRESS,
        WorkerEventType.COMPLETED,
    ]
    assert result.status is WorkerResultStatus.COMPLETED
    assert result.session_ref == "thread_1"
    assert result.usage == {"input_tokens": 3, "output_tokens": 2}
    assert result.artifacts[0].kind == "candidate_commit"


@pytest.mark.asyncio
async def test_claude_jsonl_events_are_normalized(tmp_path: Path) -> None:
    script = (
        "import json; "
        "events=[{'type':'assistant','session_id':'session_1'},"
        "{'type':'tool_use'},{'type':'tool_result'},{'type':'result'}]; "
        "[print(json.dumps(e), flush=True) for e in events]"
    )
    adapter = ClaudeWorkerAdapter(command_builder=python_jsonl(script))
    handle = await adapter.start(request(tmp_path, "claude://default"))
    events = [event async for event in adapter.stream_events(handle)]
    result = await adapter.collect_result(handle)

    assert WorkerEventType.TOOL_STARTED in [event.type for event in events]
    assert WorkerEventType.TOOL_COMPLETED in [event.type for event in events]
    assert result.status is WorkerResultStatus.COMPLETED
    assert result.session_ref == "session_1"


@pytest.mark.asyncio
async def test_process_failure_and_cancel_are_normalized(tmp_path: Path) -> None:
    failure = CodexWorkerAdapter(
        command_builder=python_jsonl(
            "import json,sys; print(json.dumps({'type':'error','message':'bad'})); sys.exit(2)"
        )
    )
    failed_handle = await failure.start(request(tmp_path))
    failed_events = [event async for event in failure.stream_events(failed_handle)]
    failed_result = await failure.collect_result(failed_handle)

    sleeping = CodexWorkerAdapter(
        command_builder=python_jsonl("import time; time.sleep(30)")
    )
    canceled_handle = await sleeping.start(request(tmp_path))
    await sleeping.cancel(canceled_handle)
    canceled_events = [event async for event in sleeping.stream_events(canceled_handle)]
    canceled_result = await sleeping.collect_result(canceled_handle)

    assert WorkerEventType.FAILED in [event.type for event in failed_events]
    assert failed_result.status is WorkerResultStatus.FAILED
    assert canceled_events[-1].type is WorkerEventType.CANCELED
    assert canceled_result.status is WorkerResultStatus.CANCELED


@pytest.mark.asyncio
async def test_external_supervisor_routes_by_agent_id(tmp_path: Path) -> None:
    adapter = CodexWorkerAdapter(
        command_builder=python_jsonl("import json; print(json.dumps({'type':'turn.completed'}))")
    )
    supervisor = ExternalLaneSupervisor({"codex://default": adapter})

    supervised = await supervisor.run(request(tmp_path))

    assert supervised.handle.adapter_id == "codex://default"
    assert supervised.result.status is WorkerResultStatus.COMPLETED
    with pytest.raises(LookupError, match="no Worker Adapter"):
        await supervisor.run(request(tmp_path, "claude://default"))
