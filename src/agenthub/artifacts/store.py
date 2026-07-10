import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from agenthub.db.models import ArtifactRecord


@dataclass(frozen=True)
class ArtifactProvenance:
    goal_id: str
    task_id: str
    run_id: str
    created_by_agent: str

    def __post_init__(self) -> None:
        if not all((self.goal_id, self.task_id, self.run_id, self.created_by_agent)):
            raise ValueError("artifact provenance requires goal, task, run, and agent")


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def publish(
        self,
        session: Session,
        *,
        provenance: ArtifactProvenance,
        kind: str,
        media_type: str,
        content: bytes,
        metadata: dict[str, object] | None = None,
    ) -> ArtifactRecord:
        if not kind.strip():
            raise ValueError("artifact kind is required")
        artifact_id = f"art_{uuid4().hex}"
        directory = self.root / provenance.goal_id / provenance.task_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / artifact_id
        temporary = directory / f".{artifact_id}.tmp"
        temporary.write_bytes(content)
        temporary.replace(path)
        record = ArtifactRecord(
            id=artifact_id,
            goal_id=provenance.goal_id,
            task_id=provenance.task_id,
            run_id=provenance.run_id,
            kind=kind,
            uri=path.as_uri(),
            sha256=hashlib.sha256(content).hexdigest(),
            media_type=media_type,
            size_bytes=len(content),
            metadata_json=metadata or {},
            created_by_agent=provenance.created_by_agent,
        )
        session.add(record)
        session.flush()
        return record
