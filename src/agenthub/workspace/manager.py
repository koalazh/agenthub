import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    path: Path
    branch: str
    base_commit: str


@dataclass(frozen=True)
class CandidateCommit:
    workspace_path: Path
    branch: str
    base_commit: str
    commit_sha: str
    changed_files: tuple[str, ...]


class WorkspaceError(RuntimeError):
    pass


class WorkspaceManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def provision(
        self,
        *,
        project_root: Path,
        default_branch: str,
        goal_id: str,
        task_id: str,
    ) -> Workspace:
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
            base_commit = self._git(project, "merge-base", branch, default_branch).strip()
            return Workspace(path=path, branch=branch, base_commit=base_commit)

        path.parent.mkdir(parents=True, exist_ok=True)
        base_commit = self._git(project, "rev-parse", default_branch).strip()
        branch_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=project,
            check=False,
        ).returncode == 0
        arguments = ["worktree", "add"]
        if not branch_exists:
            arguments.extend(["-b", branch])
        arguments.extend([str(path), branch if branch_exists else base_commit])
        self._git(project, *arguments)
        return Workspace(path=path, branch=branch, base_commit=base_commit)

    def inspect_candidate(
        self, *, workspace_path: Path, branch: str, base_commit: str
    ) -> CandidateCommit:
        workspace = workspace_path.resolve()
        actual_branch = self._git(workspace, "branch", "--show-current").strip()
        if actual_branch != branch:
            raise WorkspaceError(
                f"candidate workspace is on {actual_branch!r}, expected {branch!r}"
            )
        if self._git(workspace, "status", "--porcelain").strip():
            raise WorkspaceError("candidate workspace must be clean")
        commit_sha = self._git(workspace, "rev-parse", "HEAD").strip()
        if commit_sha == base_commit:
            raise WorkspaceError("candidate Worker did not create a commit")
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", base_commit, commit_sha],
            cwd=workspace,
            check=False,
        ).returncode
        if ancestor != 0:
            raise WorkspaceError("candidate commit is not descended from the recorded base")
        changed_files = tuple(
            line
            for line in self._git(
                workspace, "diff", "--name-only", f"{base_commit}..{commit_sha}"
            ).splitlines()
            if line
        )
        if not changed_files:
            raise WorkspaceError("candidate commit has no changed files")
        return CandidateCommit(
            workspace_path=workspace,
            branch=branch,
            base_commit=base_commit,
            commit_sha=commit_sha,
            changed_files=changed_files,
        )

    def current_commit(self, workspace_path: Path) -> str:
        return self._git(workspace_path.resolve(), "rev-parse", "HEAD").strip()

    def assert_read_only_unchanged(
        self, *, workspace_path: Path, expected_commit: str
    ) -> None:
        workspace = workspace_path.resolve()
        if self.current_commit(workspace) != expected_commit:
            raise WorkspaceError("read-only Worker changed the workspace Commit")
        if self._git(workspace, "status", "--porcelain").strip():
            raise WorkspaceError("read-only Worker modified the workspace")

    def merge_candidate(
        self,
        *,
        project_root: Path,
        default_branch: str,
        candidate: CandidateCommit,
    ) -> str:
        project = project_root.resolve()
        current_branch = self._git(project, "branch", "--show-current").strip()
        if current_branch != default_branch:
            raise WorkspaceError(
                f"project is on {current_branch!r}, expected {default_branch!r}"
            )
        current_head = self._git(project, "rev-parse", "HEAD").strip()
        if current_head == candidate.commit_sha:
            return current_head
        if current_head != candidate.base_commit:
            raise WorkspaceError("target branch HEAD changed after candidate creation")
        self._git(project, "merge", "--ff-only", candidate.commit_sha)
        return self._git(project, "rev-parse", "HEAD").strip()

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
