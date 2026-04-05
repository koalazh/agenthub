"""Per-agent APIs for operating on specific agents."""

from agenthub.api.agent.evolution import evolution, evolution_stream
from agenthub.api.agent.history import EvolutionHistoryResponse, get_evolution_history
from agenthub.api.agent.rollback import RollbackRequest, RollbackResponse, rollback_agent
from agenthub.api.agent.self_evolution import archive_count, self_evolution, self_evolution_stream

__all__ = [
    "archive_count",
    "evolution",
    "evolution_stream",
    "get_evolution_history",
    "rollback_agent",
    "self_evolution",
    "self_evolution_stream",
]
