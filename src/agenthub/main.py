import json

import typer
import uvicorn

from agenthub.api.app import create_app
from agenthub.db.migrations import upgrade_database
from agenthub.hermes.health import hermes_health
from agenthub.settings import get_settings

app = typer.Typer(no_args_is_help=True)


@app.command()
def serve() -> None:
    """Start the local AgentHub API."""
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


@app.command()
def db_upgrade() -> None:
    """Apply AgentHub database migrations."""
    upgrade_database(get_settings().database_url)


@app.command()
def doctor() -> None:
    """Inspect Hermes installation, API/Gateway, and Kanban availability."""
    import asyncio

    settings = get_settings()
    result = asyncio.run(
        hermes_health(
            source_path=settings.hermes_source_path,
            api_base_url=settings.hermes_api_base_url,
            kanban_home=settings.hermes_kanban_home,
            timeout_seconds=settings.hermes_probe_timeout_seconds,
        )
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def run() -> None:
    app()


if __name__ == "__main__":
    run()
