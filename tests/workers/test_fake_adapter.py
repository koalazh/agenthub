from pathlib import Path

import pytest

from agenthub.workers.base import WorkerEventType, WorkerResultStatus, WorkerStartRequest
from agenthub.workers.fake_adapter import FakeWorkerAdapter


def request(tmp_path: Path) -> WorkerStartRequest:
    return WorkerStartRequest(
        goal_id="goal_test",
        task_id="implement",
        kanban_task_id="t_test",
        expected_run_id=1,
        agent_id="fake://default",
        task_envelope={"output_contract": {"artifacts": ["candidate_commit"]}},
        workspace_path=tmp_path,
        timeout_seconds=60,
        artifact_output_dir=tmp_path / "artifacts",
    )


@pytest.mark.asyncio
async def test_fake_adapter_normalizes_success_events_and_result(tmp_path: Path) -> None:
    adapter = FakeWorkerAdapter()
    handle = await adapter.start(request(tmp_path))
    events = [event async for event in adapter.stream_events(handle)]
    result = await adapter.collect_result(handle)

    assert [event.type for event in events] == [
        WorkerEventType.ACCEPTED,
        WorkerEventType.STARTED,
        WorkerEventType.PROGRESS,
        WorkerEventType.ARTIFACT_CREATED,
        WorkerEventType.COMPLETED,
    ]
    assert result.status is WorkerResultStatus.COMPLETED
    assert result.artifacts[0].kind == "candidate_commit"


@pytest.mark.asyncio
async def test_fake_adapter_normalizes_failure(tmp_path: Path) -> None:
    adapter = FakeWorkerAdapter(fail=True)
    handle = await adapter.start(request(tmp_path))
    events = [event async for event in adapter.stream_events(handle)]
    result = await adapter.collect_result(handle)

    assert events[-1].type is WorkerEventType.FAILED
    assert result.status is WorkerResultStatus.FAILED
    assert result.failure.type == "PERMANENT_FAILURE"


@pytest.mark.asyncio
async def test_fake_adapter_can_be_canceled(tmp_path: Path) -> None:
    adapter = FakeWorkerAdapter()
    handle = await adapter.start(request(tmp_path))
    await adapter.cancel(handle)
    events = [event async for event in adapter.stream_events(handle)]
    result = await adapter.collect_result(handle)

    assert events[-1].type is WorkerEventType.CANCELED
    assert result.status is WorkerResultStatus.CANCELED
