from pathlib import Path

import pytest
from pydantic import ValidationError

from agenthub.registry.loader import load_registry
from agenthub.registry.models import AgentRegistryConfig
from agenthub.registry.resolver import AgentDemand, AgentResolutionError, resolve_agent

ROOT = Path(__file__).resolve().parents[2]


def test_registry_loads_capability_contracts() -> None:
    registry = load_registry(ROOT / "config" / "agents.yaml")

    assert {agent.id for agent in registry.agents} == {
        "hermes://implementer",
        "hermes://reviewer",
        "claude://default",
        "codex://default",
    }


def test_resolver_hard_filters_write_permission_and_runtime_availability() -> None:
    registry = load_registry(ROOT / "config" / "agents.yaml")

    resolved = resolve_agent(
        registry,
        AgentDemand(
            capabilities=frozenset({"code-implementation"}), repository_write=True
        ),
        available_runtimes=frozenset({"codex"}),
    )

    assert resolved.id == "codex://default"


def test_independent_review_excludes_executor() -> None:
    registry = load_registry(ROOT / "config" / "agents.yaml")

    resolved = resolve_agent(
        registry,
        AgentDemand(
            capabilities=frozenset({"code-review"}),
            repository_write=False,
            excluded_agent_ids=frozenset({"codex://default"}),
        ),
        available_runtimes=frozenset({"hermes", "codex"}),
    )

    assert resolved.id == "hermes://reviewer"


def test_requested_agent_must_still_satisfy_permissions() -> None:
    registry = load_registry(ROOT / "config" / "agents.yaml")

    with pytest.raises(AgentResolutionError):
        resolve_agent(
            registry,
            AgentDemand(
                capabilities=frozenset({"code-review"}),
                repository_write=True,
                requested_agent_id="hermes://reviewer",
            ),
            available_runtimes=frozenset({"hermes"}),
        )


def test_registry_rejects_runtime_scheme_mismatch() -> None:
    with pytest.raises(ValidationError, match="scheme must match"):
        AgentRegistryConfig.model_validate(
            {
                "agents": [
                    {
                        "id": "codex://default",
                        "runtime": "claude",
                        "capabilities": ["code-review"],
                        "constraints": {
                            "repository_write": False,
                            "max_parallel_runs": 1,
                        },
                    }
                ]
            }
        )
