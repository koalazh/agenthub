import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    path: Path
    branch: str


class WorkspaceError(RuntimeError):
    pass


class WorkspaceManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def provision(self, *, project_root: Path, goal_id: str, task_id: str) -> Workspace:
        project = project_root.resolve()
        self._git(project, "rev-parse", "--show-toplevel")
        goal_part = self._safe(goal_id.removeprefix("goal_"))[:12]
        task_part = self._safe(task_id)[:40]
        branch = f"agenthub/{goal_part}/{task_part}"
        path = self.root / goal_part / task_part
        if path.is_dir():
            actual_branch = self._git(path, "branch", "--show-current").strip()
            if actual_branch != branch:
                raise WorkspaceError(
                    f"existing workspace {path} is on {actual_branch!r}, expected {branch!r}"
                )
            return Workspace(path=path, branch=branch)

        path.parent.mkdir(parents=True, exist_ok=True)
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=project,
            check=False,
        ).returncode == 0
        arguments = ["worktree", "add"]
        if not branch_exists:
            arguments.extend(["-b", branch])
        arguments.extend([str(path), branch if branch_exists else "HEAD"])
        self._git(project, *arguments)
        return Workspace(path=path, branch=branch)

    @staticmethod
    def _safe(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
        if not cleaned:
            raise WorkspaceError("goal and task ids must contain a safe path component")
        return cleaned

    @staticmethod
    def _git(cwd: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            raise WorkspaceError(completed.stderr.strip() or completed.stdout.strip())
        return completed.stdout
