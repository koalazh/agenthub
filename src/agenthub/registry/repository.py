from sqlalchemy import select
from sqlalchemy.orm import Session

from agenthub.db.models import AgentDefinitionRecord, AgentStatsRecord
from agenthub.registry.models import AgentRegistryConfig


def sync_registry(session: Session, registry: AgentRegistryConfig) -> None:
    for definition in registry.agents:
        record = session.get(AgentDefinitionRecord, definition.id)
        if record is None:
            record = AgentDefinitionRecord(id=definition.id)
            session.add(record)
        record.runtime = definition.runtime
        record.display_name = definition.display_name
        record.enabled = definition.enabled
        record.capabilities_json = sorted(definition.capabilities)
        record.constraints_json = definition.constraints.model_dump(mode="json")
        record.config_json = {"profile": definition.profile}
        if session.get(AgentStatsRecord, definition.id) is None:
            session.add(AgentStatsRecord(agent_id=definition.id))
    session.commit()


def list_registry_records(session: Session) -> list[dict[str, object]]:
    definitions = session.scalars(
        select(AgentDefinitionRecord).order_by(AgentDefinitionRecord.id)
    ).all()
    return [
        {
            "id": definition.id,
            "runtime": definition.runtime,
            "display_name": definition.display_name,
            "enabled": definition.enabled,
            "capabilities": definition.capabilities_json,
            "constraints": definition.constraints_json,
            "config": definition.config_json,
            "stats": _stats(session.get(AgentStatsRecord, definition.id)),
        }
        for definition in definitions
    ]


def _stats(record: AgentStatsRecord | None) -> dict[str, object]:
    if record is None:
        return {}
    return {
        "completed_runs": record.completed_runs,
        "verifier_pass_count": record.verifier_pass_count,
        "verifier_total_count": record.verifier_total_count,
        "average_cost": record.average_cost,
        "average_latency_ms": record.average_latency_ms,
        "recent_failure_count": record.recent_failure_count,
        "last_used_at": record.last_used_at,
    }
