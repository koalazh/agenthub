import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


class AgentHubMCPClient:
    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=30, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, *, json: object | None = None) -> Any:
        response = self._client.request(method, path, json=json)
        if response.is_error:
            detail = response.json().get("detail", response.text)
            raise RuntimeError(f"AgentHub rejected proposal ({response.status_code}): {detail}")
        return response.json()

    def create_goal(self, proposal: dict[str, object]) -> dict[str, object]:
        return self._request("POST", "/api/goals", json=proposal)

    def submit_harness(
        self, goal_id: str, logical_ir: dict[str, object]
    ) -> dict[str, object]:
        return self._request("POST", f"/api/goals/{goal_id}/harness", json=logical_ir)

    def patch_harness(
        self, goal_id: str, proposal: dict[str, object]
    ) -> dict[str, object]:
        return self._request("POST", f"/api/goals/{goal_id}/harness/patch", json=proposal)

    def get_goal(self, goal_id: str) -> dict[str, object]:
        return self._request("GET", f"/api/goals/{goal_id}")

    def list_goals(self) -> list[dict[str, object]]:
        return self._request("GET", "/api/goals")

    def execute_goal(self, goal_id: str) -> dict[str, object]:
        return self._request("POST", f"/api/goals/{goal_id}/execute")

    def cancel_goal(self, goal_id: str) -> dict[str, object]:
        return self._request("POST", f"/api/goals/{goal_id}/cancel")

    def decide_approval(
        self, goal_id: str, approval_id: str, decision: str, comment: str | None
    ) -> dict[str, object]:
        return self._request(
            "POST",
            f"/api/goals/{goal_id}/approvals/{approval_id}",
            json={"decision": decision, "comment": comment},
        )

    def merge_goal(self, goal_id: str) -> dict[str, object]:
        return self._request("POST", f"/api/goals/{goal_id}/merge")


def _client() -> AgentHubMCPClient:
    return AgentHubMCPClient(os.environ.get("AGENTHUB_API_BASE_URL", "http://127.0.0.1:8787"))


mcp = FastMCP(
    "agenthub-control",
    instructions=(
        "Submit typed proposals to AgentHub Runtime. Tool results are observations; "
        "only Runtime commits authoritative state."
    ),
)


@mcp.tool()
def agenthub_create_goal(
    objective: str,
    project_root: str,
    acceptance_criteria: list[str],
    constraints: list[str] | None = None,
    prohibited_actions: list[str] | None = None,
    required_evidence: list[str] | None = None,
    delivery_mode: str = "candidate_commit",
) -> dict[str, object]:
    """Submit a typed Goal proposal; Runtime validates and persists it."""
    client = _client()
    try:
        return client.create_goal(
            {
                "objective": objective,
                "project_root": project_root,
                "acceptance_criteria": acceptance_criteria,
                "constraints": constraints or [],
                "prohibited_actions": prohibited_actions or [],
                "required_evidence": required_evidence,
                "delivery_mode": delivery_mode,
            }
        )
    finally:
        client.close()


@mcp.tool()
def agenthub_submit_harness(
    goal_id: str, logical_ir: dict[str, object]
) -> dict[str, object]:
    """Submit typed Harness IR v1; Runtime validates, compiles, and commits it."""
    client = _client()
    try:
        return client.submit_harness(goal_id, logical_ir)
    finally:
        client.close()


@mcp.tool()
def agenthub_patch_harness(
    goal_id: str, proposal: dict[str, object]
) -> dict[str, object]:
    """Submit a versioned Harness Patch against the active base version."""
    client = _client()
    try:
        return client.patch_harness(goal_id, proposal)
    finally:
        client.close()


@mcp.tool()
def agenthub_get_goal(goal_id: str) -> dict[str, object]:
    """Get current Goal, Harness, Task, Artifact, and Run observations."""
    client = _client()
    try:
        return client.get_goal(goal_id)
    finally:
        client.close()


@mcp.tool()
def agenthub_list_goals() -> list[dict[str, object]]:
    """List durable Goals visible to the local user."""
    client = _client()
    try:
        return client.list_goals()
    finally:
        client.close()


@mcp.tool()
def agenthub_execute_goal(goal_id: str) -> dict[str, object]:
    """Ask Runtime to launch the active validated Harness."""
    client = _client()
    try:
        return client.execute_goal(goal_id)
    finally:
        client.close()


@mcp.tool()
def agenthub_cancel_goal(goal_id: str) -> dict[str, object]:
    """Submit Goal cancellation; Runtime owns Task and Run termination."""
    client = _client()
    try:
        return client.cancel_goal(goal_id)
    finally:
        client.close()


@mcp.tool()
def agenthub_approve(
    goal_id: str,
    approval_id: str,
    decision: str,
    comment: str | None = None,
) -> dict[str, object]:
    """Resolve a pending Runtime approval as approve or reject."""
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    client = _client()
    try:
        return client.decide_approval(goal_id, approval_id, decision, comment)
    finally:
        client.close()


@mcp.tool()
def agenthub_request_merge(goal_id: str) -> dict[str, object]:
    """Ask Runtime to merge an approved, verified candidate Commit."""
    client = _client()
    try:
        return client.merge_goal(goal_id)
    finally:
        client.close()


def run() -> None:
    mcp.run(transport="stdio")
