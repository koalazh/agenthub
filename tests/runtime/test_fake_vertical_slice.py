import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agenthub.api.app import create_app
from agenthub.db.models import HarnessRunRecord, StepExecutionRecord, TaskMappingRecord
from agenthub.hermes.kanban_adapter import HermesKanbanAdapter
from agenthub.settings import Settings
from agenthub.workers.claude_adapter import ClaudeWorkerAdapter
from agenthub.workers.codex_adapter import CodexWorkerAdapter
from agenthub.workers.fake_adapter import FakeWorkerAdapter
from agenthub.workers.supervisor import ExternalLaneSupervisor
from tests.api.test_goals import create_goal
from tests.harness.test_validator import valid_harness

HERMES_SOURCE = Path(
    os.environ.get("HERMES_SOURCE_PATH", "/Users/koala/work/hermes-agent")
)
pytestmark = pytest.mark.skipif(
    not HERMES_SOURCE.is_dir(), reason="Hermes source checkout unavailable"
)


def initialize_project(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "agenthub@example.invalid"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "AgentHub Test"], cwd=path, check=True)
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=path, check=True, capture_output=True)


def runtime_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "agenthub-data",
        database_url=f"sqlite:///{tmp_path / 'agenthub.db'}",
        hermes_source_path=HERMES_SOURCE,
        hermes_kanban_home=tmp_path / "hermes-home",
        hermes_api_base_url="http://127.0.0.1:1",
        hermes_probe_timeout_seconds=0.1,
    )


def executable_harness(goal_id: str, *, gate_passes: bool = True) -> dict[str, object]:
    payload = valid_harness()
    payload["metadata"]["goal_id"] = goal_id
    exit_code = 0 if gate_passes else 2
    payload["steps"][2]["checks"] = [
        {
            "name": "tests",
            "command": f'"{sys.executable}" -c "raise SystemExit({exit_code})"',
        }
    ]
    return payload


def repair_harness(goal_id: str) -> dict[str, object]:
    payload = executable_harness(goal_id)
    payload["steps"].insert(
        -1,
        {
            "id": "repair",
            "kind": "loop",
            "depends_on": ["review"],
            "max_iterations": 2,
            "continue_when": "review_requires_changes",
            "body": {
                "agent_call": {
                    "task": "Repair review findings",
                    "selector": {"prefer_binding_from": "implement"},
                },
                "runtime_gate": {"inherit_from": "checks"},
                "review": {"inherit_from": "review"},
            },
        },
    )
    payload["steps"][-1]["depends_on"] = ["repair"]
    return payload


def parallel_harness(goal_id: str) -> dict[str, object]:
    payload = executable_harness(goal_id)
    payload["steps"][0] = {
        "id": "analysis",
        "kind": "parallel",
        "branches": [
            {
                "id": branch_id,
                "agent_call": {
                    "id": branch_id,
                    "kind": "agent_call",
                    "task": task,
                    "selector": {"capabilities": ["code-analysis"]},
                    "workspace": {"mode": "read_only"},
                    "outputs": ["analysis_report"],
                },
            }
            for branch_id, task in (
                ("code", "Inspect code"),
                ("tests", "Inspect tests"),
            )
        ],
    }
    payload["steps"][1]["depends_on"] = ["analysis"]
    return payload


def approval_harness(goal_id: str) -> dict[str, object]:
    payload = executable_harness(goal_id)
    payload["steps"].insert(
        -1,
        {
            "id": "release_approval",
            "kind": "wait_approval",
            "depends_on": ["review"],
            "approval_type": "human_input",
            "prompt": "Approve candidate finalization",
        },
    )
    payload["steps"][-1]["depends_on"] = ["release_approval"]
    return payload


def test_fake_goal_runs_through_hermes_gate_review_and_completion(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    settings = runtime_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        goal_id = create_goal(client, project)
        assert (
            client.post(
                f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id)
            ).status_code
            == 201
        )

        response = client.post(f"/api/goals/{goal_id}/execute")
        assert response.status_code == 200, response.text
        detail = response.json()

        assert detail["goal"]["status"] == "completed"
        assert detail["harness_runs"][0]["status"] == "completed"
        assert {step["status"] for step in detail["step_executions"]} == {"succeeded"}
        assert len(detail["task_mappings"]) == 5
        assert {artifact["kind"] for artifact in detail["artifacts"]} >= {
            "analysis_report",
            "candidate_commit",
            "test-log",
            "review_report",
        }
        assert detail["usage_summary"] == {
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "worker_runs": 3,
        }
        assert {(item["from_task_id"], item["to_task_id"]) for item in detail["handoffs"]} == {
            ("inspect", "implement"),
            ("implement", "checks"),
            ("review", "finalize"),
        }
        implementation_handoff = next(
            item for item in detail["handoffs"] if item["from_task_id"] == "implement"
        )
        assert implementation_handoff["artifact_refs"]
        executor = next(
            step["agent_id"]
            for step in detail["step_executions"]
            if step["step_id"] == "implement"
        )
        reviewer = next(
            step["agent_id"]
            for step in detail["step_executions"]
            if step["step_id"] == "review"
        )
        assert executor != reviewer
        candidate = next(
            artifact for artifact in detail["artifacts"] if artifact["kind"] == "candidate_commit"
        )
        artifact_response = client.get(f"/api/artifacts/{candidate['id']}")
        assert artifact_response.status_code == 200
        assert b"Fake artifact" in artifact_response.content

    worktrees = list((settings.data_dir / "worktrees").glob("*/*"))
    assert len(worktrees) == 1
    assert (
        subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=worktrees[0],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == f"agenthub/{goal_id.removeprefix('goal_')[:12]}/implement"
    )
    board = detail["task_mappings"][0]["kanban_board"]
    kanban = HermesKanbanAdapter(
        hermes_home=settings.hermes_kanban_home, source_path=HERMES_SOURCE
    )
    assert {task.status for task in kanban.list_tasks(board=board)} == {"done"}


def test_materialized_run_recovers_without_duplicate_tasks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    settings = runtime_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id))
        app.state.runtime_controller.start_goal(goal_id)
        before = client.get(f"/api/goals/{goal_id}").json()
        assert len(before["task_mappings"]) == 5

    with TestClient(create_app(settings)) as restarted_client:
        response = restarted_client.post(f"/api/goals/{goal_id}/execute")
        detail = response.json()

    assert response.status_code == 200
    assert detail["goal"]["status"] == "completed"
    assert len(detail["harness_runs"]) == 1
    assert len(detail["task_mappings"]) == 5


def test_runtime_gate_failure_prevents_goal_completion(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    with TestClient(create_app(runtime_settings(tmp_path))) as client:
        goal_id = create_goal(client, project)
        client.post(
            f"/api/goals/{goal_id}/harness",
            json=executable_harness(goal_id, gate_passes=False),
        )

        response = client.post(f"/api/goals/{goal_id}/execute")
        detail = response.json()

    assert response.status_code == 200
    assert detail["goal"]["status"] == "failed"
    assert detail["harness_runs"][0]["status"] == "failed"
    assert next(
        step["status"] for step in detail["step_executions"] if step["step_id"] == "checks"
    ) == "failed"
    assert next(
        step["status"] for step in detail["step_executions"] if step["step_id"] == "finalize"
    ) == "pending"


def test_review_rejection_runs_bounded_repair_then_completes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    app = create_app(runtime_settings(tmp_path))
    app.state.runtime_controller._fake_worker = FakeWorkerAdapter(
        review_decisions=("changes_required", "pass")
    )
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        response = client.post(
            f"/api/goals/{goal_id}/harness", json=repair_harness(goal_id)
        )
        assert response.status_code == 201, response.text

        detail = client.post(f"/api/goals/{goal_id}/execute").json()
        events = client.get(f"/api/goals/{goal_id}/events").json()

    assert detail["goal"]["status"] == "completed"
    assert len(detail["task_mappings"]) == 12
    assert {step["status"] for step in detail["step_executions"]} == {"succeeded"}
    skipped = {
        step["step_id"]
        for step in detail["step_executions"]
        if step["result"].get("skipped")
    }
    assert skipped == {"repair_repair_2", "repair_gate_2", "repair_review_2"}
    mappings = {item["step_id"]: item for item in detail["task_mappings"]}
    assert mappings["repair_repair_1"]["workspace_path"] == mappings["implement"][
        "workspace_path"
    ]
    assert mappings["repair_repair_1"]["branch_name"] == mappings["implement"][
        "branch_name"
    ]
    assert len(list((app.state.settings.data_dir / "worktrees").glob("*/*"))) == 1
    assert [
        event["payload"]["decision"]
        for event in events
        if event["type"] == "review.completed"
    ] == ["changes_required", "pass"]
    assert any(event["type"] == "loop.completed" for event in events)


def test_review_repair_limit_exhaustion_fails_goal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    app = create_app(runtime_settings(tmp_path))
    app.state.runtime_controller._fake_worker = FakeWorkerAdapter(
        review_decisions=("changes_required", "changes_required", "changes_required")
    )
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=repair_harness(goal_id))

        detail = client.post(f"/api/goals/{goal_id}/execute").json()

    assert detail["goal"]["status"] == "failed"
    assert next(
        step for step in detail["step_executions"] if step["step_id"] == "repair"
    )["result"]["failure"].startswith("Review repair limit exhausted")
    assert next(
        step["status"]
        for step in detail["step_executions"]
        if step["step_id"] == "finalize"
    ) == "pending"


def test_parallel_branches_materialize_and_join_before_implementation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    with TestClient(create_app(runtime_settings(tmp_path))) as client:
        goal_id = create_goal(client, project)
        response = client.post(
            f"/api/goals/{goal_id}/harness", json=parallel_harness(goal_id)
        )
        assert response.status_code == 201, response.text

        detail = client.post(f"/api/goals/{goal_id}/execute").json()

    assert detail["goal"]["status"] == "completed"
    assert len(detail["task_mappings"]) == 7
    executions = {step["step_id"]: step for step in detail["step_executions"]}
    assert executions["analysis_code"]["status"] == "succeeded"
    assert executions["analysis_tests"]["status"] == "succeeded"
    assert executions["analysis"]["result"] == {"branches": ["code", "tests"]}


def test_wait_approval_persists_and_resumes_harness(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    settings = runtime_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        goal_id = create_goal(client, project)
        response = client.post(
            f"/api/goals/{goal_id}/harness", json=approval_harness(goal_id)
        )
        assert response.status_code == 201, response.text

        waiting = client.post(f"/api/goals/{goal_id}/execute").json()
        approval = next(
            item for item in waiting["approvals"] if item["type"] == "human_input"
        )
        assert waiting["goal"]["status"] == "waiting"
        assert waiting["harness_runs"][0]["status"] == "waiting"
        assert next(
            step["status"]
            for step in waiting["step_executions"]
            if step["step_id"] == "release_approval"
        ) == "waiting"

    with TestClient(create_app(settings)) as restarted_client:
        decision = restarted_client.post(
            f"/api/goals/{goal_id}/approvals/{approval['id']}",
            json={"decision": "approve", "comment": "Proceed"},
        )
        assert decision.status_code == 200, decision.text
        completed = restarted_client.post(f"/api/goals/{goal_id}/execute").json()

    assert completed["goal"]["status"] == "completed"
    assert next(
        step["result"]
        for step in completed["step_executions"]
        if step["step_id"] == "release_approval"
    )["approved"] is True


def test_rejected_wait_approval_fails_harness(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    with TestClient(create_app(runtime_settings(tmp_path))) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=approval_harness(goal_id))
        waiting = client.post(f"/api/goals/{goal_id}/execute").json()
        approval = next(
            item for item in waiting["approvals"] if item["type"] == "human_input"
        )

        decision = client.post(
            f"/api/goals/{goal_id}/approvals/{approval['id']}",
            json={"decision": "reject", "comment": "Stop"},
        )
        detail = client.get(f"/api/goals/{goal_id}").json()

    assert decision.status_code == 200
    assert detail["goal"]["status"] == "failed"
    assert next(
        step["status"]
        for step in detail["step_executions"]
        if step["step_id"] == "release_approval"
    ) == "failed"


def test_worker_failure_is_committed_by_runtime_not_adapter(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    app = create_app(runtime_settings(tmp_path))
    app.state.runtime_controller._fake_worker = FakeWorkerAdapter(fail=True)
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id))

        detail = client.post(f"/api/goals/{goal_id}/execute").json()

    assert detail["goal"]["status"] == "failed"
    assert next(
        step["status"] for step in detail["step_executions"] if step["step_id"] == "inspect"
    ) == "failed"


def test_reported_worker_cost_cannot_exceed_harness_budget(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    app = create_app(runtime_settings(tmp_path))
    app.state.runtime_controller._fake_worker = FakeWorkerAdapter(
        usage={"input_tokens": 10, "output_tokens": 5, "cost_usd": 25.0}
    )
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id))

        detail = client.post(f"/api/goals/{goal_id}/execute").json()

    assert detail["goal"]["status"] == "failed"
    assert detail["usage_summary"]["cost_usd"] == 25.0
    assert next(
        step["result"]["failure"]
        for step in detail["step_executions"]
        if step["status"] == "failed"
    ) == "Harness cost budget exceeded"


def test_wall_time_budget_is_enforced_after_restart(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    app = create_app(runtime_settings(tmp_path))
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id))
        run_id = app.state.runtime_controller.start_goal(goal_id)
        with app.state.session_factory() as session:
            run = session.get(HarnessRunRecord, run_id)
            run.started_at = datetime.now(UTC) - timedelta(seconds=3601)
            session.commit()

        detail = client.post(f"/api/goals/{goal_id}/execute").json()

    assert detail["goal"]["status"] == "failed"
    assert next(
        step["result"]["failure"]
        for step in detail["step_executions"]
        if step["status"] == "failed"
    ) == "Harness wall-time budget exceeded"


def test_restart_reconciliation_terminates_lost_worker_supervision(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    settings = runtime_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id))
        run_id = app.state.runtime_controller.start_goal(goal_id)
        with app.state.session_factory() as session:
            execution = session.query(StepExecutionRecord).filter_by(
                harness_run_id=run_id, step_id="inspect"
            ).one()
            mapping = session.query(TaskMappingRecord).filter_by(
                harness_run_id=run_id, step_id="inspect"
            ).one()
            claimed = app.state.runtime_controller._kanban.claim_task(
                board=mapping.kanban_board,
                task_id=mapping.kanban_task_id,
                claimer="lost-controller",
                ttl_seconds=900,
            )
            execution.status = "running"
            execution.started_at = datetime.now(UTC)
            mapping.expected_run_id = claimed.current_run_id
            session.commit()

    with TestClient(create_app(settings)) as restarted_client:
        detail = restarted_client.get(f"/api/goals/{goal_id}").json()

    assert detail["goal"]["status"] == "failed"
    assert detail["harness_runs"][0]["status"] == "failed"
    assert "Runtime restart" in next(
        step["result"]["failure"]
        for step in detail["step_executions"]
        if step["step_id"] == "inspect"
    )
    board = detail["task_mappings"][0]["kanban_board"]
    kanban = HermesKanbanAdapter(
        hermes_home=settings.hermes_kanban_home, source_path=HERMES_SOURCE
    )
    assert kanban.list_tasks(board=board) == []


def test_cancel_archives_materialized_kanban_tasks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    app = create_app(runtime_settings(tmp_path))
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id))
        app.state.runtime_controller.start_goal(goal_id)

        response = client.post(f"/api/goals/{goal_id}/cancel")
        detail = response.json()

    assert response.status_code == 200
    assert detail["goal"]["status"] == "canceled"
    assert detail["harness_runs"][0]["status"] == "canceled"
    assert {step["status"] for step in detail["step_executions"]} == {"canceled"}
    board = detail["task_mappings"][0]["kanban_board"]
    kanban = HermesKanbanAdapter(
        hermes_home=runtime_settings(tmp_path).hermes_kanban_home,
        source_path=HERMES_SOURCE,
    )
    assert not kanban.list_tasks(board=board)


@pytest.mark.parametrize(
    ("lane", "implementation_agent"),
    [
        ("hermes", "hermes://implementer"),
        ("claude", "claude://default"),
        ("codex", "codex://default"),
    ],
)
def test_same_harness_materializes_to_configured_worker_lane(
    tmp_path: Path, lane: str, implementation_agent: str
) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    settings = runtime_settings(tmp_path)
    settings = settings.model_copy(update={"default_worker_lane": lane})
    app = create_app(settings)
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id))

        app.state.runtime_controller.start_goal(goal_id)
        detail = client.get(f"/api/goals/{goal_id}").json()

    assert next(
        step["agent_id"]
        for step in detail["step_executions"]
        if step["step_id"] == "implement"
    ) == implementation_agent
    reviewer = next(
        step["agent_id"]
        for step in detail["step_executions"]
        if step["step_id"] == "review"
    )
    assert reviewer != implementation_agent
    assert len(detail["task_mappings"]) == 5


def test_hermes_lane_executes_through_native_dispatcher(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    settings = runtime_settings(tmp_path).model_copy(update={"default_worker_lane": "hermes"})
    for profile in ("hermes-implementer", "hermes-reviewer"):
        (settings.hermes_kanban_home / "profiles" / profile).mkdir(parents=True)
    app = create_app(settings)

    def spawn(task: object, _: str, *, board: str) -> None:
        if task.title.endswith(": implement"):
            workspace = Path(task.workspace_path)
            (workspace / "hermes-change.txt").write_text("candidate\n", encoding="utf-8")
            subprocess.run(["git", "add", "hermes-change.txt"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "commit", "-m", "feat: hermes candidate"],
                cwd=workspace,
                check=True,
                capture_output=True,
            )
        summary = (
            '{"decision":"pass","findings":[]}'
            if task.assignee == "hermes-reviewer"
            else f"Hermes completed {task.title}"
        )
        assert app.state.runtime_controller._kanban.complete(
            board=board,
            task_id=task.id,
            expected_run_id=task.current_run_id,
            summary=summary,
            metadata={},
        )

    app.state.runtime_controller._hermes_spawn_fn = spawn
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        client.post(f"/api/goals/{goal_id}/harness", json=executable_harness(goal_id))

        response = client.post(f"/api/goals/{goal_id}/execute")
        detail = response.json()

    assert response.status_code == 200, response.text
    assert detail["goal"]["status"] == "completed"
    agents = {step["agent_id"] for step in detail["step_executions"]}
    assert "hermes://implementer" in agents
    assert "hermes://reviewer" in agents
    candidate = next(
        artifact for artifact in detail["artifacts"] if artifact["kind"] == "candidate_commit"
    )
    assert candidate["metadata"]["commit_sha"]


def test_codex_implementation_and_claude_review_execute_through_supervisor(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    settings = runtime_settings(tmp_path).model_copy(update={"default_worker_lane": "codex"})
    app = create_app(settings)
    def command(worker_request: object, output: Path) -> list[str]:
        if worker_request.task_id == "implement":
            script = (
                "import json,subprocess; from pathlib import Path; "
                "Path('implemented.txt').write_text('candidate\\n'); "
                "subprocess.run(['git','add','implemented.txt'],check=True); "
                "subprocess.run(['git','commit','-m','feat: candidate'],check=True); "
                "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1}}))"
            )
        elif "review" in worker_request.task_id:
            script = (
                "import json; from pathlib import Path; "
                f"Path({str(output)!r}).write_text(json.dumps("
                "{'decision':'pass','findings':[]})); "
                "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1}}))"
            )
        else:
            script = (
                "import json; "
                "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1}}))"
            )
        return [
            sys.executable,
            "-c",
            script,
        ]
    supervisor = ExternalLaneSupervisor(
        {
            "codex://default": CodexWorkerAdapter(command_builder=command),
            "claude://default": ClaudeWorkerAdapter(command_builder=command),
        }
    )
    app.state.runtime_controller._external_supervisor = supervisor
    with TestClient(app) as client:
        goal_id = create_goal(client, project)
        harness = executable_harness(goal_id)
        harness["steps"][3]["selector"]["agent_id"] = "claude://default"
        client.post(f"/api/goals/{goal_id}/harness", json=harness)

        response = client.post(f"/api/goals/{goal_id}/execute")
        detail = response.json()
        agents = client.get("/api/agents").json()
        approval = detail["approvals"][0]
        before_approval = client.post(f"/api/goals/{goal_id}/merge")
        approval_response = client.post(
            f"/api/goals/{goal_id}/approvals/{approval['id']}",
            json={"decision": "approve", "comment": "Ship it"},
        )
        repeated_approval = client.post(
            f"/api/goals/{goal_id}/approvals/{approval['id']}",
            json={"decision": "approve", "comment": "Repeated"},
        )
        merge_response = client.post(f"/api/goals/{goal_id}/merge")
        repeated_merge = client.post(f"/api/goals/{goal_id}/merge")

    assert response.status_code == 200, response.text
    assert detail["goal"]["status"] == "completed"
    candidate = next(
        artifact for artifact in detail["artifacts"] if artifact["kind"] == "candidate_commit"
    )
    assert candidate["metadata"]["commit_sha"]
    assert candidate["metadata"]["changed_files"] == ["implemented.txt"]
    assert before_approval.status_code == 409
    assert approval_response.json()["status"] == "approved"
    assert repeated_approval.json()["status"] == "approved"
    assert merge_response.status_code == 200
    assert repeated_merge.json() == merge_response.json()
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == candidate["metadata"]["commit_sha"]
    )
    assert next(agent for agent in agents if agent["id"] == "codex://default")["stats"][
        "completed_runs"
    ] == 2
    claude_stats = next(agent for agent in agents if agent["id"] == "claude://default")[
        "stats"
    ]
    assert claude_stats["verifier_total_count"] == 1
    assert claude_stats["verifier_pass_count"] == 1
