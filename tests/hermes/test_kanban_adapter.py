from pathlib import Path

import pytest

from agenthub.hermes.kanban_adapter import (
    HermesKanbanAdapter,
    HermesKanbanCompatibilityError,
    project_board_slug,
    task_body,
)

HERMES_SOURCE = Path("/Users/koala/work/hermes-agent")


def test_project_board_slug_is_stable_and_bounded(tmp_path: Path) -> None:
    project = tmp_path / ("Project Name " * 10)

    first = project_board_slug(project)
    second = project_board_slug(project)

    assert first == second
    assert first.startswith("agenthub-project-name-")
    assert len(first) <= 64


def test_task_body_contains_machine_readable_header() -> None:
    body = task_body(
        goal_id="goal_test",
        harness_version=2,
        step_id="implement",
        objective="Implement the fix",
        acceptance_criteria=("Tests pass",),
        output_contract=("candidate_commit",),
    )

    assert "goal_id: goal_test" in body
    assert "harness_version: 2" in body
    assert "step_id: implement" in body
    assert "task_contract_version: 1" in body


@pytest.mark.skipif(not HERMES_SOURCE.is_dir(), reason="Hermes source checkout unavailable")
def test_real_hermes_kanban_lifecycle_and_idempotency(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    adapter = HermesKanbanAdapter(
        hermes_home=tmp_path / "hermes-home", source_path=HERMES_SOURCE
    )
    board = adapter.ensure_board(project_root=project)
    body = task_body(
        goal_id="goal_test",
        harness_version=1,
        step_id="inspect",
        objective="Inspect",
        acceptance_criteria=("Report exists",),
        output_contract=("analysis_report",),
    )

    task_id = adapter.create_task(
        board=board,
        title="Inspect",
        body=body,
        assignee="agenthub:fake",
        parents=(),
        idempotency_key="goal_test:1:inspect:1",
        workspace_kind="dir",
        workspace_path=str(project),
    )
    duplicate_id = adapter.create_task(
        board=board,
        title="Inspect duplicate",
        body=body,
        assignee="agenthub:fake",
        parents=(),
        idempotency_key="goal_test:1:inspect:1",
        workspace_kind="dir",
        workspace_path=str(project),
    )
    claimed = adapter.claim_task(
        board=board, task_id=task_id, claimer="agenthub-test", ttl_seconds=60
    )

    assert duplicate_id == task_id
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.current_run_id is not None
    assert adapter.heartbeat(
        board=board, task_id=task_id, claimer="agenthub-test", ttl_seconds=60
    )
    assert not adapter.complete(
        board=board,
        task_id=task_id,
        expected_run_id=claimed.current_run_id + 1,
        summary="Stale completion",
        metadata={},
    )
    assert adapter.get_task(board=board, task_id=task_id).status == "running"
    assert adapter.complete(
        board=board,
        task_id=task_id,
        expected_run_id=claimed.current_run_id,
        summary="Inspection complete",
        metadata={"artifacts": ["analysis.md"]},
    )
    assert adapter.get_task(board=board, task_id=task_id).status == "done"
    assert [event.kind for event in adapter.list_events(board=board, task_id=task_id)] == [
        "created",
        "claimed",
        "completed",
    ]


def test_incompatible_hermes_surface_is_rejected(tmp_path: Path) -> None:
    from types import ModuleType

    module = ModuleType("incomplete_hermes")

    with pytest.raises(HermesKanbanCompatibilityError, match="missing required functions"):
        HermesKanbanAdapter(hermes_home=tmp_path, module=module)
