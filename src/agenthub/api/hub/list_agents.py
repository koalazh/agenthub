"""List Agents API."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from agenthub.core.config import get_config
from agenthub.core.types import Agent

logger = logging.getLogger(__name__)


async def list_agents() -> list[Agent]:
    """List all agents.

    Returns:
        List of Agent objects
    """
    logger.info("Listing all agents")

    config = get_config()
    agenthub_dir = config.agenthub_dir

    if not agenthub_dir.exists():
        return []

    agents: list[Agent] = []

    for agent_dir in agenthub_dir.iterdir():
        if not agent_dir.is_dir():
            continue

        # Skip hidden directories
        if agent_dir.name.startswith("."):
            continue

        agent_id = agent_dir.name
        metadata_file = agent_dir / ".agenthub_meta"
        name = agent_id
        created_at = datetime.now(timezone.utc)

        if metadata_file.exists():
            try:
                metadata = json.loads(metadata_file.read_text())
                name = metadata.get("name", agent_id)
                created_at = datetime.fromisoformat(metadata.get("created_at", datetime.now(timezone.utc).isoformat()))
            except Exception as e:
                logger.warning(f"Failed to read agent metadata for {agent_id}: {e}")

        agents.append(Agent(
            id=agent_id,
            name=name,
            path=agent_dir,
            created_at=created_at,
        ))

    # Sort by creation time, newest first
    agents.sort(key=lambda a: a.created_at, reverse=True)

    return agents
