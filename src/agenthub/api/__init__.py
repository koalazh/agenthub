"""Public API for AgentHub.

This module re-exports from the new structure for backwards compatibility.
New code should import from agenthub.api.hub or agenthub.api.agent directly.
"""

# Re-export from new locations for backwards compatibility
from agenthub.api.agent import (
    archive_count,
    evolution,
    evolution_stream,
    get_evolution_history,
    rollback_agent,
    self_evolution,
    self_evolution_stream,
)
from agenthub.api.hub import (
    delete_agent,
    export_agent_config,
    get_agent,
    init_agent,
    list_agents,
)

__all__ = [
    "archive_count",
    "delete_agent",
    "evolution",
    "evolution_stream",
    "export_agent_config",
    "get_agent",
    "get_evolution_history",
    "init_agent",
    "list_agents",
    "rollback_agent",
    "self_evolution",
    "self_evolution_stream",
]
