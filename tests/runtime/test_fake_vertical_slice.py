import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agenthub.api.app import create_app
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


def test_codex_implementation_and_claude_review_execute_through_supervisor(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    initialize_project(project)
    settings = runtime_settings(tmp_path).model_copy(update={"default_worker_lane": "codex"})
    app = create_app(settings)
    def command(worker_request: object, _output: Path) -> list[str]:
        if worker_request.task_id == "implement":
            script = (
                "import json,subprocess; from pathlib import Path; "
                "Path('implemented.txt').write_text('candidate\\n'); "
                "subprocess.run(['git','add','implemented.txt'],check=True); "
                "subprocess.run(['git','commit','-m','feat: candidate'],check=True); "
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
