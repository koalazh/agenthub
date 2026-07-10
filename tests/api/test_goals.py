from pathlib import Path

from fastapi.testclient import TestClient

from agenthub.api.app import create_app
from agenthub.api.goals import encode_sse_events
from agenthub.settings import Settings
from tests.harness.test_validator import valid_harness


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'agenthub.db'}",
        hermes_api_base_url="http://127.0.0.1:1",
        hermes_probe_timeout_seconds=0.1,
    )


def create_goal(client: TestClient, project_root: Path) -> str:
    response = client.post(
        "/api/goals",
        json={
            "objective": "Fix refresh race",
            "project_root": str(project_root),
            "acceptance_criteria": ["Regression test passes"],
            "constraints": ["Do not change the public API"],
            "required_evidence": ["Test output", "Independent review"],
        },
    )
    assert response.status_code == 201
    return response.json()["goal_id"]


def harness_for(goal_id: str) -> dict[str, object]:
    payload = valid_harness()
    payload["metadata"]["goal_id"] = goal_id
    return payload


def test_sse_encoding_resumes_after_last_event_id() -> None:
    messages, cursor = encode_sse_events(
        [
            {"id": 1, "type": "goal.created", "payload": {}},
            {"id": 2, "type": "harness.activated", "payload": {"version": 1}},
        ],
        cursor=1,
    )

    assert cursor == 2
    assert len(messages) == 1
    assert messages[0].startswith("id: 2\nevent: harness.activated\n")
    assert '"version": 1' in messages[0]


def patch_with_approval() -> dict[str, object]:
    return {
        "base_version": 1,
        "reason": "Require explicit launch approval",
        "operations": [
            {
                "op": "add_step",
                "after": "review",
                "step": {
                    "id": "approval",
                    "kind": "wait_approval",
                    "depends_on": ["review"],
                    "approval_type": "harness_launch",
                    "prompt": "Approve final delivery",
                },
            },
            {
                "op": "replace_step",
                "step_id": "finalize",
                "step": {
                    "id": "finalize",
                    "kind": "finalize",
                    "depends_on": ["approval"],
                    "delivery": "candidate_commit",
                },
            },
        ],
    }


def test_create_goal_submit_harness_and_restore_after_restart(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings)) as client:
        goal_id = create_goal(client, tmp_path)
        response = client.post(f"/api/goals/{goal_id}/harness", json=harness_for(goal_id))
        assert response.status_code == 201
        assert response.json()["version"] == 1
        assert [step["id"] for step in response.json()["compilation"]["steps"]] == [
            "inspect",
            "implement",
            "checks",
            "review",
            "finalize",
        ]

    with TestClient(create_app(settings)) as restarted_client:
        detail = restarted_client.get(f"/api/goals/{goal_id}").json()

    assert detail["goal"]["status"] == "planned"
    assert detail["current_harness_version"]["version"] == 1
    assert len(detail["harness_versions"]) == 1


def test_patch_creates_immutable_auditable_version(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        goal_id = create_goal(client, tmp_path)
        initial = client.post(
            f"/api/goals/{goal_id}/harness", json=harness_for(goal_id)
        ).json()

        response = client.post(
            f"/api/goals/{goal_id}/harness/patch", json=patch_with_approval()
        )
        detail = client.get(f"/api/goals/{goal_id}").json()
        events = client.get(f"/api/goals/{goal_id}/events").json()

    assert response.status_code == 201
    assert response.json()["version"] == 2
    assert response.json()["parent_version_id"] == initial["id"]
    assert [version["status"] for version in detail["harness_versions"]] == [
        "superseded",
        "active",
    ]
    assert len(detail["harness_versions"][0]["logical_ir"]["steps"]) == 5
    assert len(detail["harness_versions"][1]["logical_ir"]["steps"]) == 6
    assert detail["harness_versions"][0]["semantic_hash"] == (
        detail["harness_versions"][1]["semantic_hash"]
    )
    assert [event["type"] for event in events] == [
        "goal.created",
        "harness.proposed",
        "harness.validated",
        "harness.activated",
        "harness.proposed",
        "harness.validated",
        "harness.activated",
    ]


def test_stale_patch_is_rejected_without_new_version(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        goal_id = create_goal(client, tmp_path)
        client.post(f"/api/goals/{goal_id}/harness", json=harness_for(goal_id))
        assert (
            client.post(
                f"/api/goals/{goal_id}/harness/patch", json=patch_with_approval()
            ).status_code
            == 201
        )

        stale = client.post(
            f"/api/goals/{goal_id}/harness/patch", json=patch_with_approval()
        )
        detail = client.get(f"/api/goals/{goal_id}").json()

    assert stale.status_code == 409
    assert len(detail["harness_versions"]) == 2


def test_invalid_patch_does_not_replace_active_harness(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        goal_id = create_goal(client, tmp_path)
        client.post(f"/api/goals/{goal_id}/harness", json=harness_for(goal_id))

        response = client.post(
            f"/api/goals/{goal_id}/harness/patch",
            json={
                "base_version": 1,
                "reason": "Remove mandatory review",
                "operations": [{"op": "remove_step", "step_id": "review"}],
            },
        )
        detail = client.get(f"/api/goals/{goal_id}").json()

    assert response.status_code == 422
    assert detail["current_harness_version"]["version"] == 1
    assert len(detail["harness_versions"]) == 1


def test_harness_goal_id_must_match_endpoint(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        goal_id = create_goal(client, tmp_path)
        response = client.post(
            f"/api/goals/{goal_id}/harness", json=valid_harness()
        )

    assert response.status_code == 422
    assert "goal_id" in str(response.json()["detail"])


def test_harness_patch_count_is_bounded(tmp_path: Path) -> None:
    with TestClient(create_app(settings_for(tmp_path))) as client:
        goal_id = create_goal(client, tmp_path)
        harness = harness_for(goal_id)
        harness["bounds"]["max_patch_versions"] = 1
        client.post(f"/api/goals/{goal_id}/harness", json=harness)
        client.post(f"/api/goals/{goal_id}/harness/patch", json=patch_with_approval())

        second_patch = patch_with_approval()
        second_patch["base_version"] = 2
        response = client.post(
            f"/api/goals/{goal_id}/harness/patch", json=second_patch
        )

    assert response.status_code == 409
    assert "limit" in response.json()["detail"]
