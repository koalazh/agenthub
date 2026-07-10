import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from agenthub.api.app import create_app
from tests.api.test_goals import create_goal, settings_for


def test_chat_proxies_hermes_run_and_links_goal_session(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(202, json={"run_id": "run_123", "status": "started"})
        return httpx.Response(
            200,
            json={"object": "hermes.run", "run_id": "run_123", "status": "completed"},
        )

    app = create_app(settings_for(tmp_path))
    app.state.hermes_http_transport = httpx.MockTransport(handler)
    with TestClient(app) as client:
        goal_id = create_goal(client, tmp_path)
        response = client.post(
            "/api/chat",
            json={
                "input": "Continue this Goal",
                "goal_id": goal_id,
                "session_key": "agent:main:web:local",
                "channel": "web",
            },
        )
        status = client.get("/api/chat/runs/run_123")
        detail = client.get(f"/api/goals/{goal_id}").json()

    assert response.status_code == 202
    assert response.json()["goal_id"] == goal_id
    assert status.json()["status"] == "completed"
    assert json.loads(seen[0].content) == {
        "input": "Continue this Goal",
        "session_id": "agent:main:web:local",
    }
    assert detail["session_links"][0]["session_key"] == "agent:main:web:local"


def test_chat_surfaces_upstream_rejection_without_claiming_success(tmp_path: Path) -> None:
    app = create_app(settings_for(tmp_path))
    app.state.hermes_http_transport = httpx.MockTransport(
        lambda _: httpx.Response(429, json={"error": {"message": "busy"}})
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"input": "Start", "session_key": "web:local"},
        )

    assert response.status_code == 502
    assert response.json()["detail"]["upstream_status"] == 429
