import contextlib
import hashlib
import importlib
import os
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

REQUIRED_KANBAN_API = (
    "create_board",
    "connect",
    "create_task",
    "get_task",
    "list_tasks",
    "claim_task",
    "heartbeat_claim",
    "complete_task",
    "block_task",
    "archive_task",
    "dispatch_once",
    "add_comment",
    "list_events",
)


class HermesKanbanCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class KanbanTaskSnapshot:
    id: str
    status: str
    assignee: str | None
    current_run_id: int | None
    workspace_kind: str
    workspace_path: str | None


@dataclass(frozen=True)
class KanbanEventSnapshot:
    id: int
    kind: str
    payload: dict[str, Any] | None
    run_id: int | None


def project_board_slug(project_root: Path) -> str:
    digest = hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()[:8]
    name = "".join(
        character if character.isalnum() else "-" for character in project_root.name.lower()
    ).strip("-")
    name = name[:40] or "project"
    return f"agenthub-{name}-{digest}"


def task_body(
    *,
    goal_id: str,
    harness_version: int,
    step_id: str,
    objective: str,
    acceptance_criteria: tuple[str, ...],
    output_contract: tuple[str, ...],
) -> str:
    criteria = "\n".join(f"- {item}" for item in acceptance_criteria)
    outputs = "\n".join(f"- {item}" for item in output_contract)
    return (
        "---\n"
        "agenthub:\n"
        f"  goal_id: {goal_id}\n"
        f"  harness_version: {harness_version}\n"
        f"  step_id: {step_id}\n"
        "  task_contract_version: 1\n"
        "---\n\n"
        f"## Objective\n\n{objective}\n\n"
        f"## Acceptance Criteria\n\n{criteria}\n\n"
        f"## Output Contract\n\n{outputs}\n"
    )


class HermesKanbanAdapter:
    _environment_lock = threading.RLock()

    def __init__(
        self,
        *,
        hermes_home: Path,
        source_path: Path | None = None,
        module: ModuleType | None = None,
    ) -> None:
        self.hermes_home = hermes_home.resolve()
        self._module = module or self._load_module(source_path)
        missing = [name for name in REQUIRED_KANBAN_API if not hasattr(self._module, name)]
        if missing:
            raise HermesKanbanCompatibilityError(
                f"Hermes Kanban API is missing required functions: {', '.join(missing)}"
            )

    @staticmethod
    def _load_module(source_path: Path | None) -> ModuleType:
        if source_path is not None:
            source = str(source_path.resolve())
            if source not in sys.path:
                sys.path.insert(0, source)
        try:
            return importlib.import_module("hermes_cli.kanban_db")
        except ImportError as exc:
            raise HermesKanbanCompatibilityError(
                "Hermes Kanban could not be imported; configure a compatible source checkout"
            ) from exc

    @contextlib.contextmanager
    def _environment(self) -> Iterator[None]:
        with self._environment_lock:
            previous = os.environ.get("HERMES_KANBAN_HOME")
            previous_home = os.environ.get("HERMES_HOME")
            os.environ["HERMES_KANBAN_HOME"] = str(self.hermes_home)
            os.environ["HERMES_HOME"] = str(self.hermes_home)
            try:
                yield
            finally:
                if previous is None:
                    os.environ.pop("HERMES_KANBAN_HOME", None)
                else:
                    os.environ["HERMES_KANBAN_HOME"] = previous
                if previous_home is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = previous_home

    @contextlib.contextmanager
    def _connection(self, board: str) -> Iterator[Any]:
        with self._environment():
            connection = self._module.connect(board=board)
            try:
                yield connection
            finally:
                connection.close()

    def ensure_board(self, *, project_root: Path) -> str:
        board = project_board_slug(project_root)
        with self._environment():
            self._module.create_board(
                board,
                name=f"AgentHub {project_root.name}",
                default_workdir=str(project_root.resolve()),
            )
        return board

    def create_task(
        self,
        *,
        board: str,
        title: str,
        body: str,
        assignee: str,
        parents: tuple[str, ...],
        idempotency_key: str,
        workspace_kind: str,
        workspace_path: str | None = None,
        branch_name: str | None = None,
        max_runtime_seconds: int | None = None,
    ) -> str:
        with self._connection(board) as connection:
            return self._module.create_task(
                connection,
                title=title,
                body=body,
                assignee=assignee,
                created_by="agenthub-runtime",
                parents=parents,
                idempotency_key=idempotency_key,
                workspace_kind=workspace_kind,
                workspace_path=workspace_path,
                branch_name=branch_name,
                max_runtime_seconds=max_runtime_seconds,
                board=board,
            )

    def get_task(self, *, board: str, task_id: str) -> KanbanTaskSnapshot | None:
        with self._connection(board) as connection:
            task = self._module.get_task(connection, task_id)
        return self._snapshot(task) if task is not None else None

    def list_tasks(self, *, board: str, status: str | None = None) -> list[KanbanTaskSnapshot]:
        with self._connection(board) as connection:
            tasks = self._module.list_tasks(connection, status=status)
        return [self._snapshot(task) for task in tasks]

    def claim_task(
        self, *, board: str, task_id: str, claimer: str, ttl_seconds: int
    ) -> KanbanTaskSnapshot | None:
        with self._connection(board) as connection:
            task = self._module.claim_task(
                connection, task_id, claimer=claimer, ttl_seconds=ttl_seconds
            )
        return self._snapshot(task) if task is not None else None

    def heartbeat(
        self, *, board: str, task_id: str, claimer: str, ttl_seconds: int
    ) -> bool:
        with self._connection(board) as connection:
            return self._module.heartbeat_claim(
                connection, task_id, claimer=claimer, ttl_seconds=ttl_seconds
            )

    def complete(
        self,
        *,
        board: str,
        task_id: str,
        expected_run_id: int,
        summary: str,
        metadata: dict[str, Any],
    ) -> bool:
        with self._connection(board) as connection:
            return self._module.complete_task(
                connection,
                task_id,
                summary=summary,
                metadata=metadata,
                expected_run_id=expected_run_id,
            )

    def block(
        self,
        *,
        board: str,
        task_id: str,
        expected_run_id: int,
        reason: str,
    ) -> bool:
        with self._connection(board) as connection:
            return self._module.block_task(
                connection, task_id, reason=reason, expected_run_id=expected_run_id
            )

    def archive(self, *, board: str, task_id: str) -> bool:
        with self._connection(board) as connection:
            return self._module.archive_task(connection, task_id)

    def add_comment(self, *, board: str, task_id: str, author: str, body: str) -> int:
        with self._connection(board) as connection:
            return self._module.add_comment(connection, task_id, author, body)

    def dispatch_once(
        self,
        *,
        board: str,
        spawn_fn: Any = None,
        max_spawn: int | None = None,
        max_in_progress: int | None = None,
    ) -> Any:
        with self._connection(board) as connection:
            return self._module.dispatch_once(
                connection,
                spawn_fn=spawn_fn,
                max_spawn=max_spawn,
                max_in_progress=max_in_progress,
                board=board,
            )

    def list_events(self, *, board: str, task_id: str) -> list[KanbanEventSnapshot]:
        with self._connection(board) as connection:
            events = self._module.list_events(connection, task_id)
        return [
            KanbanEventSnapshot(
                id=event.id,
                kind=event.kind,
                payload=event.payload,
                run_id=event.run_id,
            )
            for event in events
        ]

    @staticmethod
    def _snapshot(task: Any) -> KanbanTaskSnapshot:
        return KanbanTaskSnapshot(
            id=task.id,
            status=task.status,
            assignee=task.assignee,
            current_run_id=task.current_run_id,
            workspace_kind=task.workspace_kind,
            workspace_path=task.workspace_path,
        )
