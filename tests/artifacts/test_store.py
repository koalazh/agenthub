import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from agenthub.artifacts.store import ArtifactProvenance, ArtifactStore
from agenthub.db.base import create_database_engine
from agenthub.db.migrations import upgrade_database
from agenthub.db.models import GoalRecord


def test_artifact_store_persists_content_hash_and_provenance(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'agenthub.db'}"
    upgrade_database(database_url)
    engine = create_database_engine(database_url)
    content = b"test output\n"
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            GoalRecord(
                id="goal_test",
                title="Test",
                objective="Test",
                status="running",
                owner_user_id="local-user",
                project_root=str(tmp_path),
                default_branch="main",
                delivery_mode="candidate_commit",
                contract_json={},
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.flush()
        record = ArtifactStore(tmp_path / "artifacts").publish(
            session,
            provenance=ArtifactProvenance(
                goal_id="goal_test",
                task_id="checks",
                run_id="run_1",
                created_by_agent="agenthub://runtime",
            ),
            kind="test-log",
            media_type="text/plain",
            content=content,
        )
        session.commit()

    assert Path(record.uri.removeprefix("file://")).read_bytes() == content
    assert record.sha256 == hashlib.sha256(content).hexdigest()
    assert record.goal_id == "goal_test"
    assert record.task_id == "checks"
    assert record.run_id == "run_1"
    assert record.created_by_agent == "agenthub://runtime"


def test_artifact_provenance_is_mandatory() -> None:
    with pytest.raises(ValueError, match="requires goal, task, run, and agent"):
        ArtifactProvenance(
            goal_id="goal_test", task_id="checks", run_id="", created_by_agent="runtime"
        )
