import shutil

from fastapi import APIRouter, Request

from agenthub.registry.repository import list_registry_records

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
def list_agents(request: Request) -> list[dict[str, object]]:
    available = {
        "hermes": request.app.state.settings.hermes_source_path is not None,
        "claude": shutil.which("claude") is not None,
        "codex": shutil.which("codex") is not None,
    }
    with request.app.state.session_factory() as session:
        records = list_registry_records(session)
    for record in records:
        record["available"] = available.get(str(record["runtime"]), False)
    return records
