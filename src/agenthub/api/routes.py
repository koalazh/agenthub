"""FastAPI HTTP routes for AgentHub.

This module exposes the Python API as HTTP endpoints for external callers
like agentcenter.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

from agenthub.api.agent.evolution import evolution as run_evolution
from agenthub.api.agent.self_evolution import self_evolution as run_self_evolution
from agenthub.api.agent.self_evolution import self_evolution_stream as run_self_evolution_stream
from agenthub.api.agent.self_evolution import archive_count as run_archive_count
from agenthub.api.agent.rollback import rollback_agent as run_rollback
from agenthub.api.agent.rollback import RollbackRequest
from agenthub.api.agent.history import get_evolution_history as run_get_history
from agenthub.api.hub.export import export_agent_config as run_export
from agenthub.api.hub.delete_agent import delete_agent as run_delete_agent
from agenthub.api.hub.get_agent import get_agent as run_get_agent
from agenthub.api.hub.init_agent import init_agent as run_init_agent
from agenthub.api.hub.list_agents import list_agents as run_list_agents
from agenthub.core.errors import (
    AgentHubError,
    NotFoundError,
    SecurityError,
    ValidationError,
)
from agenthub.core.types import (
    Agent,
    InitAgentConfig,
    RawTranscriptInput,
    SelfEvolutionResult,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="AgentHub API",
    description="HTTP API for AgentHub - AI Agent Growth Platform",
    version="0.1.0",
)


# === Exception Mapping ===

def _map_exception_to_status_code(exc: Exception) -> tuple[int, str]:
    """Map exception to HTTP status code and error code.

    Returns:
        (status_code, error_code)
    """
    if isinstance(exc, NotFoundError):
        return 404, "AGENT_NOT_FOUND"
    if isinstance(exc, SecurityError):
        return 403, "PERMISSION_DENIED"
    if isinstance(exc, (ValidationError, PydanticValidationError)):
        return 422, "VALIDATION_ERROR"
    if isinstance(exc, AgentHubError):
        msg = exc.message.lower()
        if "already exists" in msg:
            return 409, "AGENT_ALREADY_EXISTS"
        if "invalid commit" in msg or "target not found" in msg:
            return 404, "TARGET_NOT_FOUND"
        if "already at target" in msg:
            return 400, "ALREADY_AT_TARGET"
        if "git operation failed" in msg:
            return 500, "GIT_OPERATION_FAILED"
        return 500, "INTERNAL_ERROR"
    return 500, "INTERNAL_ERROR"


# === Agent Management Routes ===

@app.post("/agents", response_model=dict[str, Any])
async def create_agent(config: InitAgentConfig) -> dict[str, Any]:
    """Create a new agent.

    Args:
        config: Agent initialization configuration

    Returns:
        Created agent info with agent_id
    """
    try:
        agent: Agent = await run_init_agent(config)
        return {
            "agent_id": agent.id,
            "name": agent.name,
            "version": "v1.0",
            "created_at": agent.created_at.isoformat(),
        }
    except AgentHubError as e:
        status, code = _map_exception_to_status_code(e)
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


@app.get("/agents", response_model=list[dict[str, Any]])
async def list_all_agents() -> list[dict[str, Any]]:
    """List all agents.

    Returns:
        List of agent info dictionaries
    """
    agents = await run_list_agents()
    return [
        {
            "agent_id": a.id,
            "name": a.name,
            "created_at": a.created_at.isoformat(),
        }
        for a in agents
    ]


@app.get("/agents/{agent_id}", response_model=dict[str, Any])
async def get_agent_by_id(agent_id: str) -> dict[str, Any]:
    """Get agent details.

    Args:
        agent_id: Agent ID

    Returns:
        Agent details
    """
    try:
        agent = await run_get_agent(agent_id)
        return {
            "agent_id": agent.id,
            "name": agent.name,
            "path": str(agent.path),
            "created_at": agent.created_at.isoformat(),
            "avatar": agent.avatar,
        }
    except AgentHubError as e:
        status, code = _map_exception_to_status_code(e)
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


@app.delete("/agents/{agent_id}", response_model=dict[str, Any])
async def delete_agent_by_id(agent_id: str) -> dict[str, Any]:
    """Delete an agent.

    Args:
        agent_id: Agent ID

    Returns:
        Deletion confirmation
    """
    try:
        await run_delete_agent(agent_id)
        return {"agent_id": agent_id, "deleted": True}
    except AgentHubError as e:
        status, code = _map_exception_to_status_code(e)
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


# === Evolution Routes ===

@app.get("/evolution/archive-count", response_model=dict[str, Any])
async def get_archive_count(
    agent_id: str = Query(..., description="Agent ID"),
) -> dict[str, Any]:
    """Get the count of archives since last self-evolution.

    Args:
        agent_id: Agent ID

    Returns:
        Archive count info
    """
    try:
        count = await run_archive_count(agent_id)
        return {"agent_id": agent_id, "archive_count": count}
    except AgentHubError as e:
        status, code = _map_exception_to_status_code(e)
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


@app.post("/evolution/start", response_model=dict[str, Any])
async def start_evolution(
    agent_id: str,
    session_id: str,
    transcript: str,
    task_summary: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Trigger evolution analysis after task completion.

    Args:
        agent_id: Agent ID
        session_id: Unique session ID for this execution
        transcript: Task execution transcript (max 1MB)
        task_summary: Summary of the task
        project_id: Optional project identifier

    Returns:
        Evolution result
    """
    # Truncate transcript if too large (by bytes, not chars)
    max_size = 1048576  # 1MB
    encoded = transcript.encode("utf-8")
    if len(encoded) > max_size:
        transcript = encoded[:max_size].decode("utf-8", errors="ignore")

    raw_input = RawTranscriptInput(
        id=session_id,
        content=transcript,
        project_id=project_id,
    )

    try:
        result = await run_evolution(agent_id, raw_input)
        return {
            "evolution_id": session_id,
            "status": "completed" if result.should_record else "no_record_needed",
            "result": {
                "form": result.form,
                "scope": result.scope,
                "skill_name": result.skill_name,
                "commit_hash": result.commit_hash,
            } if result.should_record else None,
        }
    except AgentHubError as e:
        status, code = _map_exception_to_status_code(e)
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


@app.post("/self-evolution/start", response_model=dict[str, Any])
async def start_self_evolution(
    agent_id: str,
    lookback_days: int = Query(default=7, ge=1, le=90),
    force_reanalyze: bool = False,
) -> dict[str, Any]:
    """Trigger batch self-evolution analysis.

    Args:
        agent_id: Agent ID
        lookback_days: Number of days to look back
        force_reanalyze: Whether to re-analyze existing skills

    Returns:
        Self-evolution result with stats
    """
    try:
        result: SelfEvolutionResult = await run_self_evolution(agent_id)
        return {
            "evolution_id": f"self-ev-{agent_id}",
            "status": "completed",
            "stats": {
                "tasks_analyzed": 0,  # Not tracked in current impl
                "skills_created": len([c for c in result.changes if c.type == "add_skill"]),
                "gaps_filled": len([c for c in result.changes if c.type == "update_skill"]),
                "duplicates_merged": 0,  # Not tracked in current impl
            },
        }
    except AgentHubError as e:
        status, code = _map_exception_to_status_code(e)
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


# === Export Route ===

@app.get("/export/claude-code", response_model=dict[str, Any])
async def export_claude_code_config(
    agent_id: str = Query(..., description="Agent ID"),
    project_id: str | None = Query(default=None, description="Project ID for filtering"),
) -> dict[str, Any]:
    """Export Claude Code CLI configuration for an agent.

    Args:
        agent_id: Agent ID
        project_id: Optional project ID to filter skills/memory

    Returns:
        ClaudeCodeLaunchConfig as dictionary
    """
    try:
        config = await run_export(agent_id, project_id)
        return config.model_dump()
    except AgentHubError as e:
        status, code = _map_exception_to_status_code(e)
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


# === Rollback Route ===

@app.post("/evolution/rollback", response_model=dict[str, Any])
async def rollback_evolution(
    agent_id: str,
    target: str,
) -> dict[str, Any]:
    """Rollback agent to a previous commit.

    Args:
        agent_id: Agent ID
        target: Target: 'HEAD~N' or commit hash

    Returns:
        RollbackResponse as dictionary
    """
    try:
        request = RollbackRequest(agent_id=agent_id, target=target)
        response = await run_rollback(request)
        return response.model_dump()
    except (AgentHubError, PydanticValidationError) as e:
        status, code = _map_exception_to_status_code(e)
        if isinstance(e, PydanticValidationError):
            raise HTTPException(status_code=status, detail={"error_code": code, "message": str(e)})
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


# === History Route ===

@app.get("/evolution/history", response_model=dict[str, Any])
async def get_history(
    agent_id: str = Query(..., description="Agent ID"),
    limit: int = Query(default=20, ge=1, le=100, description="Max records to return"),
    offset: int = Query(default=0, ge=0, description="Records to skip"),
) -> dict[str, Any]:
    """Get evolution history for an agent.

    Args:
        agent_id: Agent ID
        limit: Maximum records to return
        offset: Records to skip

    Returns:
        EvolutionHistoryResponse as dictionary
    """
    try:
        response = await run_get_history(agent_id, limit, offset)
        return {
            "records": [
                {
                    "evolution_id": r.evolution_id,
                    "timestamp": r.timestamp.isoformat(),
                    "form": r.form,
                    "skill_name": r.skill_name,
                    "commit_hash": r.commit_hash,
                    "message": r.message,
                }
                for r in response.records
            ],
            "total": response.total,
            "has_more": response.has_more,
        }
    except AgentHubError as e:
        status, code = _map_exception_to_status_code(e)
        raise HTTPException(status_code=status, detail={"error_code": code, "message": e.message})


# === Health Check ===

@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Health status
    """
    return {"status": "healthy"}


# === Root ===

@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint.

    Returns:
        API info
    """
    return {
        "name": "AgentHub API",
        "version": "0.1.0",
        "docs": "/docs",
    }
