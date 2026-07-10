from pathlib import Path

from fastapi.testclient import TestClient

from agenthub.api.app import create_app
from tests.api.test_goals import settings_for


def test_agent_registry_is_persisted_and_exposed(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        first = client.get("/api/agents")

    with TestClient(create_app(settings)) as restarted_client:
        second = restarted_client.get("/api/agents")

    assert first.status_code == 200
    assert first.json() == second.json()
    assert {agent["id"] for agent in first.json()} == {
        "hermes://implementer",
        "hermes://reviewer",
        "claude://default",
        "codex://default",
    }
    assert all("stats" in agent and "available" in agent for agent in first.json())
