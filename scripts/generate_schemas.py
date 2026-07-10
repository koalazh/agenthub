import json
from pathlib import Path

from agenthub.context.handoff import Handoff
from agenthub.context.task_envelope import TaskEnvelope
from agenthub.harness.schema import ProgressiveHarness


def main() -> None:
    schema_dir = Path(__file__).resolve().parents[1] / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    schemas = {
        "harness-v1.schema.json": ProgressiveHarness.model_json_schema(),
        "task-envelope-v1.schema.json": TaskEnvelope.model_json_schema(by_alias=True),
        "handoff-v1.schema.json": Handoff.model_json_schema(),
    }
    for filename, schema in schemas.items():
        (schema_dir / filename).write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
