import subprocess
from pathlib import Path

from agenthub.workspace.manager import WorkspaceManager


def initialize_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agenthub@example.invalid"], cwd=path)
    subprocess.run(["git", "config", "user.name", "AgentHub Test"], cwd=path)
    (path / "file.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=path, check=True, capture_output=True)


def test_write_tasks_get_distinct_idempotent_worktrees(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_repo(project)
    manager = WorkspaceManager(tmp_path / "worktrees")

    first = manager.provision(project_root=project, goal_id="goal_abcdef", task_id="one")
    second = manager.provision(project_root=project, goal_id="goal_abcdef", task_id="two")
    repeated = manager.provision(project_root=project, goal_id="goal_abcdef", task_id="one")

    assert first == repeated
    assert first.path != second.path
    assert first.branch != second.branch
    assert first.path.is_dir()
    assert second.path.is_dir()
