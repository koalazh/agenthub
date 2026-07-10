import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agenthub.context.handoff import MAX_HANDOFF_BYTES, Handoff
from agenthub.context.projector import project_task_envelope
from agenthub.context.task_envelope import TaskEnvelope
from agenthub.harness.validator import parse_harness
from tests.domain.test_goal import make_goal
from tests.harness.test_validator import valid_harness


def test_worker_receives_local_projection_not_global_harness(tmp_path: Path) -> None:
    goal = make_goal(tmp_path)
    harness = parse_harness(valid_harness())
    step = next(step for step in harness.steps if step.id == "implement")

    envelope = project_task_envelope(
        goal=goal,
        run_id="hr_test",
        step=step,
        workspace_path=tmp_path / "worktree",
        artifact_refs=("artifact://analysis",),
    )
    payload = envelope.model_dump(mode="json", by_alias=True)

    assert payload["identity"]["task_id"] == "implement"
    assert payload["constraints"]["permissions"]["repository"] == "write_candidate"
    assert payload["inputs"]["artifacts"] == ["artifact://analysis"]
    assert "steps" not in payload
    assert "bounds" not in payload
    assert "mandatory_gates" not in payload


def test_handoff_is_bounded() -> None:
    with pytest.raises(ValidationError, match=str(MAX_HANDOFF_BYTES)):
        Handoff(summary="x" * (MAX_HANDOFF_BYTES + 1), confidence=1)


def test_committed_context_schemas_match_models() -> None:
    schema_dir = Path(__file__).resolve().parents[2] / "schemas"

    assert json.loads((schema_dir / "task-envelope-v1.schema.json").read_text()) == (
        TaskEnvelope.model_json_schema(by_alias=True)
    )
    assert json.loads((schema_dir / "handoff-v1.schema.json").read_text()) == (
        Handoff.model_json_schema()
    )
