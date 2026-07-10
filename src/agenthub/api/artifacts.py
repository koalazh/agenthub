from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from agenthub.db.models import ArtifactRecord

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}")
def get_artifact(artifact_id: str, request: Request) -> FileResponse:
    with request.app.state.session_factory() as session:
        artifact = session.get(ArtifactRecord, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        parsed = urlparse(artifact.uri)
        if parsed.scheme != "file":
            raise HTTPException(status_code=410, detail="artifact URI is unsupported")
        path = Path(unquote(parsed.path))
        if not path.is_file():
            raise HTTPException(status_code=410, detail="artifact content is unavailable")
        return FileResponse(path, media_type=artifact.media_type, filename=path.name)
