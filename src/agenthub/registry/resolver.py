from dataclasses import dataclass

from agenthub.registry.models import AgentDefinition, AgentRegistryConfig


@dataclass(frozen=True)
class AgentDemand:
    capabilities: frozenset[str]
    repository_write: bool
    excluded_agent_ids: frozenset[str] = frozenset()
    requested_agent_id: str | None = None


class AgentResolutionError(LookupError):
    pass


def resolve_agent(
    registry: AgentRegistryConfig,
    demand: AgentDemand,
    *,
    available_runtimes: frozenset[str],
) -> AgentDefinition:
    candidates = []
    for order, agent in enumerate(registry.agents):
        if not agent.enabled or agent.runtime not in available_runtimes:
            continue
        if demand.requested_agent_id is not None and agent.id != demand.requested_agent_id:
            continue
        if agent.id in demand.excluded_agent_ids:
            continue
        if not demand.capabilities.issubset(agent.capabilities):
            continue
        if demand.repository_write and not agent.constraints.repository_write:
            continue
        extra_capabilities = len(agent.capabilities - demand.capabilities)
        candidates.append((extra_capabilities, order, agent))
    if not candidates:
        raise AgentResolutionError("no enabled, available Agent satisfies the capability contract")
    return min(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]
