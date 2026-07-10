import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agenthub import __version__
from agenthub.api.agents import router as agents_router
from agenthub.api.approvals import router as approvals_router
from agenthub.api.artifacts import router as artifacts_router
from agenthub.api.goals import router as goals_router
from agenthub.artifacts.store import ArtifactStore
from agenthub.db.base import check_database, create_database_engine, create_session_factory
from agenthub.db.migrations import upgrade_database
from agenthub.hermes.health import hermes_health
from agenthub.hermes.kanban_adapter import (
    HermesKanbanAdapter,
    HermesKanbanCompatibilityError,
)
from agenthub.registry.loader import load_registry
from agenthub.registry.repository import sync_registry
from agenthub.runtime.controller import RuntimeController
from agenthub.settings import Settings, get_settings
from agenthub.workers.claude_adapter import ClaudeWorkerAdapter
from agenthub.workers.codex_adapter import CodexWorkerAdapter
from agenthub.workers.supervisor import ExternalLaneSupervisor
from agenthub.workspace.manager import WorkspaceManager


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    engine = create_database_engine(active_settings.database_url)
    session_factory = create_session_factory(engine)
    registry = load_registry(active_settings.agent_registry_path)
    available_runtimes = {
        runtime
        for runtime, available in {
            "hermes": active_settings.hermes_source_path is not None,
            "claude": shutil.which("claude") is not None,
            "codex": shutil.which("codex") is not None,
        }.items()
        if available
    }

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        upgrade_database(active_settings.database_url)
        with session_factory() as session:
            sync_registry(session, registry)
        if app.state.runtime_controller is not None:
            app.state.runtime_controller.recover_active_runs()
        yield
        engine.dispose()

    app = FastAPI(title="AgentHub", version=__version__, lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.settings = active_settings
    app.state.registry = registry
    external_adapters = {}
    if "claude" in available_runtimes:
        external_adapters["claude://default"] = ClaudeWorkerAdapter()
    if "codex" in available_runtimes:
        external_adapters["codex://default"] = CodexWorkerAdapter()
    app.state.external_lane_supervisor = ExternalLaneSupervisor(external_adapters)
    app.state.workspace_manager = WorkspaceManager(active_settings.data_dir / "worktrees")
    app.state.runtime_controller = None
    app.state.runtime_error = None
    if active_settings.hermes_source_path is not None:
        try:
            app.state.runtime_controller = RuntimeController(
                session_factory=session_factory,
                kanban=HermesKanbanAdapter(
                    hermes_home=active_settings.hermes_kanban_home,
                    source_path=active_settings.hermes_source_path,
                ),
                artifacts=ArtifactStore(active_settings.data_dir / "artifacts"),
                workspaces=app.state.workspace_manager,
                registry=registry,
                available_runtimes=frozenset(available_runtimes),
                default_worker_lane=active_settings.default_worker_lane,
                external_supervisor=app.state.external_lane_supervisor,
            )
        except HermesKanbanCompatibilityError as exc:
            app.state.runtime_error = str(exc)
    else:
        app.state.runtime_error = "AGENTHUB_HERMES_SOURCE_PATH is not configured"
    app.include_router(agents_router)
    app.include_router(approvals_router)
    app.include_router(artifacts_router)
    app.include_router(goals_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        database = check_database(engine)
        return {
            "status": "ok" if database["status"] == "ok" else "unavailable",
            "service": "agenthub",
            "version": __version__,
        }

    @app.get("/health/detailed")
    async def detailed_health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "agenthub",
            "version": __version__,
            "database": check_database(engine),
            "hermes": await hermes_health(
                source_path=active_settings.hermes_source_path,
                api_base_url=active_settings.hermes_api_base_url,
                kanban_home=active_settings.hermes_kanban_home,
                timeout_seconds=active_settings.hermes_probe_timeout_seconds,
            ),
        }

    return app
