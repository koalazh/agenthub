import json

from pydantic import Field, model_validator

from agenthub.context.task_envelope import FrozenModel

MAX_HANDOFF_BYTES = 8 * 1024


class Handoff(FrozenModel):
    summary: str = Field(min_length=1)
    decisions: tuple[str, ...] = ()
    claims: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def enforce_size_limit(self) -> "Handoff":
        size = len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False).encode())
        if size > MAX_HANDOFF_BYTES:
            raise ValueError(f"handoff exceeds {MAX_HANDOFF_BYTES} byte limit")
        return self
