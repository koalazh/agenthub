from pathlib import Path

import yaml

from agenthub.registry.models import AgentRegistryConfig


def load_registry(path: Path) -> AgentRegistryConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Agent Registry must be a YAML mapping")
    return AgentRegistryConfig.model_validate(payload)
