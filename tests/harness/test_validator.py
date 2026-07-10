import json
from copy import deepcopy
from pathlib import Path

import pytest

from agenthub.harness.compiler import compile_harness
from agenthub.harness.schema import ProgressiveHarness
from agenthub.harness.validator import (
    HarnessPolicy,
    HarnessValidationError,
    parse_harness,
    validate_harness,
)


def valid_harness() -> dict[str, object]:
    return {
        "api_version": "agenthub.io/harness/v1",
        "kind": "ProgressiveHarness",
        "metadata": {"name": "fix-refresh", "goal_id": "goal_test"},
        "bounds": {
            "max_parallelism": 2,
            "max_agent_runs": 8,
            "max_patch_versions": 5,
            "max_loop_iterations": 2,
            "max_wall_time_seconds": 3600,
            "max_cost_usd": 20,
        },
        "mandatory_gates": ["tests", "independent_review"],
        "steps": [
            {
                "id": "inspect",
                "kind": "agent_call",
                "task": "Inspect the bug",
                "selector": {"capabilities": ["code-analysis"]},
                "workspace": {"mode": "read_only"},
                "outputs": ["analysis_report"],
            },
            {
                "id": "implement",
                "kind": "agent_call",
                "depends_on": ["inspect"],
                "task": "Implement the fix",
                "selector": {"capabilities": ["code-implementation"]},
                "workspace": {"mode": "write_candidate"},
                "outputs": ["candidate_commit"],
            },
            {
                "id": "checks",
                "kind": "runtime_gate",
                "depends_on": ["implement"],
                "checks": [{"name": "tests", "command": "pytest -q"}],
            },
            {
                "id": "review",
                "kind": "review",
                "depends_on": ["checks"],
                "selector": {
                    "capabilities": ["code-review"],
                    "exclude_agents_from": ["implement"],
                },
                "inputs": ["candidate_commit", "checks"],
                "outputs": ["review_report"],
            },
            {
                "id": "finalize",
                "kind": "finalize",
                "depends_on": ["review"],
                "delivery": "candidate_commit",
            },
        ],
    }


def test_valid_harness_is_accepted() -> None:
    harness = parse_harness(valid_harness())

    validate_harness(harness, goal_id="goal_test")

    assert harness.metadata.goal_id == "goal_test"


def test_unknown_node_kind_is_rejected() -> None:
    payload = valid_harness()
    payload["steps"][0]["kind"] = "arbitrary_python"

    with pytest.raises(HarnessValidationError, match="arbitrary_python"):
        parse_harness(payload)


def test_missing_mandatory_gate_is_rejected() -> None:
    payload = valid_harness()
    payload["mandatory_gates"] = ["tests"]

    with pytest.raises(HarnessValidationError, match="independent_review"):
        parse_harness(payload)


def test_unknown_dependency_is_rejected() -> None:
    payload = valid_harness()
    payload["steps"][-1]["depends_on"] = ["missing"]
    harness = parse_harness(payload)

    with pytest.raises(HarnessValidationError, match="unknown dependencies"):
        validate_harness(harness, goal_id="goal_test")


def test_dependency_cycle_is_rejected() -> None:
    payload = valid_harness()
    payload["steps"][0]["depends_on"] = ["finalize"]
    harness = parse_harness(payload)

    with pytest.raises(HarnessValidationError, match="dependency cycle"):
        validate_harness(harness, goal_id="goal_test")


def test_runtime_policy_rejects_excessive_bounds() -> None:
    payload = valid_harness()
    payload["bounds"]["max_parallelism"] = 4
    harness = parse_harness(payload)

    with pytest.raises(HarnessValidationError, match="max_parallelism"):
        validate_harness(harness, goal_id="goal_test", policy=HarnessPolicy(max_parallelism=3))


def test_review_must_exclude_executor() -> None:
    payload = valid_harness()
    payload["steps"][3]["selector"]["exclude_agents_from"] = []
    harness = parse_harness(payload)

    with pytest.raises(HarnessValidationError, match="exclude an executor"):
        validate_harness(harness, goal_id="goal_test")


def test_static_agent_run_bound_is_enforced() -> None:
    payload = valid_harness()
    payload["bounds"]["max_agent_runs"] = 2
    harness = parse_harness(payload)

    with pytest.raises(HarnessValidationError, match="static agent run upper bound"):
        validate_harness(harness, goal_id="goal_test")


def test_payload_does_not_accept_untyped_extra_fields() -> None:
    payload = deepcopy(valid_harness())
    payload["steps"][0]["python"] = "import os"

    with pytest.raises(HarnessValidationError, match="Extra inputs are not permitted"):
        parse_harness(payload)


def test_loop_inherits_existing_gate_review_and_binding() -> None:
    payload = valid_harness()
    payload["steps"].insert(
        -1,
        {
            "id": "repair",
            "kind": "loop",
            "depends_on": ["review"],
            "max_iterations": 2,
            "continue_when": "review_requires_changes",
            "body": {
                "agent_call": {
                    "task": "Repair review findings",
                    "selector": {"prefer_binding_from": "implement"},
                },
                "runtime_gate": {"inherit_from": "checks"},
                "review": {"inherit_from": "review"},
            },
        },
    )
    payload["steps"][-1]["depends_on"] = ["repair"]
    harness = parse_harness(payload)

    validate_harness(harness, goal_id="goal_test")

    plan = compile_harness(harness)
    assert [step.id for step in plan.steps] == [
        "inspect",
        "implement",
        "checks",
        "review",
        "repair_repair_1",
        "repair_gate_1",
        "repair_review_1",
        "repair_repair_2",
        "repair_gate_2",
        "repair_review_2",
        "repair",
        "finalize",
    ]


def test_loop_cannot_inherit_unknown_gate() -> None:
    payload = valid_harness()
    payload["steps"].insert(
        -1,
        {
            "id": "repair",
            "kind": "loop",
            "depends_on": ["review"],
            "max_iterations": 1,
            "continue_when": "review_requires_changes",
            "body": {
                "agent_call": {
                    "task": "Repair review findings",
                    "selector": {"prefer_binding_from": "implement"},
                },
                "runtime_gate": {"inherit_from": "missing"},
                "review": {"inherit_from": "review"},
            },
        },
    )
    harness = parse_harness(payload)

    with pytest.raises(HarnessValidationError, match="unknown runtime gate"):
        validate_harness(harness, goal_id="goal_test")


def test_committed_json_schema_matches_model() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "harness-v1.schema.json"

    assert json.loads(schema_path.read_text(encoding="utf-8")) == (
        ProgressiveHarness.model_json_schema()
    )


def test_every_step_must_contribute_to_finalize() -> None:
    payload = valid_harness()
    payload["steps"].insert(
        -1,
        {
            "id": "orphan",
            "kind": "wait_approval",
            "depends_on": ["review"],
            "approval_type": "human_input",
            "prompt": "Unused approval",
        },
    )
    harness = parse_harness(payload)

    with pytest.raises(HarnessValidationError, match="do not contribute to finalize"):
        validate_harness(harness, goal_id="goal_test")
