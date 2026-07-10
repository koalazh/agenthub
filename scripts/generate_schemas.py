import json
from pathlib import Path

from agenthub.harness.schema import ProgressiveHarness


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "schemas" / "harness-v1.schema.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(ProgressiveHarness.model_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
