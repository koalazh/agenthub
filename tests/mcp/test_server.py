import httpx
import pytest

from agenthub.mcp.server import AgentHubMCPClient, mcp


def test_mcp_client_surfaces_runtime_validation_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": ["missing independent_review"]})

    client = AgentHubMCPClient("http://agenthub.test", transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError, match="missing independent_review"):
        client.submit_harness("goal_test", {})

    client.close()


def test_mcp_client_uses_proposal_endpoints() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"goal_id": "goal_test", "status": "draft"})

    client = AgentHubMCPClient("http://agenthub.test", transport=httpx.MockTransport(handler))
    result = client.create_goal(
        {
            "objective": "Fix race",
            "project_root": "/repo",
            "acceptance_criteria": ["tests pass"],
        }
    )
    client.close()

    assert result["goal_id"] == "goal_test"
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/api/goals"


@pytest.mark.asyncio
async def test_mcp_exposes_only_agenthub_control_tools() -> None:
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert names == {
        "agenthub_create_goal",
        "agenthub_submit_harness",
        "agenthub_patch_harness",
        "agenthub_get_goal",
        "agenthub_list_goals",
        "agenthub_execute_goal",
        "agenthub_cancel_goal",
        "agenthub_approve",
        "agenthub_request_merge",
    }
