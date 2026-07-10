import os
from pathlib import Path

import pytest

from agenthub.hermes.kanban_adapter import HermesKanbanAdapter
from agenthub.workers.base import WorkerEventType, WorkerResultStatus, WorkerStartRequest
from agenthub.workers.hermes_adapter import HermesProfileWorkerAdapter

HERMES_SOURCE = Path(
    os.environ.get("HERMES_SOURCE_PATH", "/Users/koala/work/hermes-agent")
)
pytestmark = pytest.mark.skipif(
    not HERMES_SOURCE.is_dir(), reason="Hermes source checkout unavailable"
)


def request(tmp_path: Path, task_id: str) -> WorkerStartRequest:
    return WorkerStartRequest(
        goal_id="goal_test",
        task_id="review",
        kanban_task_id=task_id,
        expected_run_id=0,
        agent_id="hermes://reviewer",
        task_envelope={"output_contract": {"artifacts": ["review_report"]}},
        workspace_path=tmp_path,
        timeout_seconds=60,
        artifact_output_dir=tmp_path / "artifacts",
    )


def setup_task(tmp_path: Path) -> tuple[HermesKanbanAdapter, str, str]:
    home = tmp_path / "hermes-home"
    (home / "profiles" / "hermes-reviewer").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    kanban = HermesKanbanAdapter(hermes_home=home, source_path=HERMES_SOURCE)
    board = kanban.ensure_board(project_root=project)
    task_id = kanban.create_task(
        board=board,
        title="Review candidate",
        body="Review",
        assignee="hermes-reviewer",
        parents=(),
        idempotency_key="goal_test:review:1",
        workspace_kind="dir",
        workspace_path=str(project),
    )
    return kanban, board, task_id


@pytest.mark.asyncio
async def test_hermes_adapter_reuses_dispatcher_and_normalizes_events(tmp_path: Path) -> None:
    kanban, board, task_id = setup_task(tmp_path)

    def spawn(task: object, _: str, *, board: str) -> None:
        assert task.current_run_id is not None
        assert kanban.complete(
            board=board,
            task_id=task.id,
            expected_run_id=task.current_run_id,
            summary='{"decision":"pass","findings":[]}',
            metadata={"decision": "pass"},
        )

    adapter = HermesProfileWorkerAdapter(
        kanban=kanban,
        board=board,
        agent_id="hermes://reviewer",
        profile="hermes-reviewer",
        spawn_fn=spawn,
    )
    handle = await adapter.start(request(tmp_path, task_id))
    events = [event async for event in adapter.stream_events(handle)]
    repeated_events = [event async for event in adapter.stream_events(handle)]
    result = await adapter.collect_result(handle)

    assert [event.type for event in events] == [
        WorkerEventType.ACCEPTED,
        WorkerEventType.STARTED,
        WorkerEventType.COMPLETED,
    ]
    assert result.status is WorkerResultStatus.COMPLETED
    assert result.session_ref == f"hermes-kanban://{board}/{task_id}"
    assert result.artifacts[0].kind == "review_report"
    assert b'"decision": "pass"' in result.artifacts[0].content
    assert repeated_events == []


@pytest.mark.asyncio
async def test_hermes_adapter_input_and_cancel_use_kanban_kernel(tmp_path: Path) -> None:
    kanban, board, task_id = setup_task(tmp_path)
    adapter = HermesProfileWorkerAdapter(
        kanban=kanban,
        board=board,
        agent_id="hermes://reviewer",
        profile="hermes-reviewer",
        spawn_fn=lambda *_args, **_kwargs: None,
    )
    handle = await adapter.start(request(tmp_path, task_id))
    await adapter.send_input(handle, {"message": "Check the public API"})
    await adapter.cancel(handle)
    events = [event async for event in adapter.stream_events(handle)]
    result = await adapter.collect_result(handle)

    assert events[-1].type is WorkerEventType.CANCELED
    assert result.status is WorkerResultStatus.CANCELED
    assert kanban.get_task(board=board, task_id=task_id).status == "archived"
