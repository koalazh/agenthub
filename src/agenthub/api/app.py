from contextlib import asynccontextmanager

from fastapi import FastAPI

from agenthub import __version__
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
from agenthub.runtime.controller import RuntimeController
from agenthub.settings import Settings, get_settings
from agenthub.workspace.manager import WorkspaceManager


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    engine = create_database_engine(active_settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        upgrade_database(active_settings.database_url)
        if app.state.runtime_controller is not None:
            app.state.runtime_controller.recover_active_runs()
        yield
        engine.dispose()

    app = FastAPI(title="AgentHub", version=__version__, lifespan=lifespan)
    app.state.session_factory = session_factory
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
                workspaces=WorkspaceManager(active_settings.data_dir / "worktrees"),
            )
        except HermesKanbanCompatibilityError as exc:
            app.state.runtime_error = str(exc)
    else:
        app.state.runtime_error = "AGENTHUB_HERMES_SOURCE_PATH is not configured"
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
