import subprocess
from pathlib import Path

import pytest

from agenthub.workspace.manager import WorkspaceError, WorkspaceManager


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

    first = manager.provision(
        project_root=project, default_branch="main", goal_id="goal_abcdef", task_id="one"
    )
    second = manager.provision(
        project_root=project, default_branch="main", goal_id="goal_abcdef", task_id="two"
    )
    repeated = manager.provision(
        project_root=project, default_branch="main", goal_id="goal_abcdef", task_id="one"
    )

    assert first == repeated
    assert first.path != second.path
    assert first.branch != second.branch
    assert first.path.is_dir()
    assert second.path.is_dir()


def test_candidate_requires_clean_commit_and_rejects_target_drift(tmp_path: Path) -> None:
    project = tmp_path / "project"
    initialize_repo(project)
    manager = WorkspaceManager(tmp_path / "worktrees")
    workspace = manager.provision(
        project_root=project,
        default_branch="main",
        goal_id="goal_abcdef",
        task_id="implement",
    )
    (workspace.path / "change.txt").write_text("change\n", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="clean"):
        manager.inspect_candidate(
            workspace_path=workspace.path,
            branch=workspace.branch,
            base_commit=workspace.base_commit,
        )

    subprocess.run(["git", "add", "change.txt"], cwd=workspace.path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: candidate"],
        cwd=workspace.path,
        check=True,
        capture_output=True,
    )
    candidate = manager.inspect_candidate(
        workspace_path=workspace.path,
        branch=workspace.branch,
        base_commit=workspace.base_commit,
    )
    (project / "drift.txt").write_text("drift\n", encoding="utf-8")
    subprocess.run(["git", "add", "drift.txt"], cwd=project, check=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: drift"], cwd=project, check=True, capture_output=True
    )

    with pytest.raises(WorkspaceError, match="HEAD changed"):
        manager.merge_candidate(
            project_root=project, default_branch="main", candidate=candidate
        )
