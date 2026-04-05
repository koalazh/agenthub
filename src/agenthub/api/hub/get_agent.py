"""Get Agent API."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from agenthub.core.config import get_config
from agenthub.core.errors import NotFoundError
from agenthub.core.types import Agent

logger = logging.getLogger(__name__)


async def get_agent(agent_id: str) -> Agent:
    """Get an agent by ID.

    Args:
        agent_id: ID of the agent to retrieve

    Returns:
        Agent object

    Raises:
        NotFoundError: If agent is not found
    """
    logger.info(f"Getting agent: {agent_id}")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id

    if not agent_dir.exists():
        raise NotFoundError(f"Agent '{agent_id}' not found")

    # Try to read agent metadata
    metadata_file = agent_dir / ".agenthub_meta"
    name = agent_id
    created_at = datetime.now(timezone.utc)
    avatar = None

    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text())
            name = metadata.get("name", agent_id)
            created_at = datetime.fromisoformat(metadata.get("created_at", datetime.now(timezone.utc).isoformat()))
            avatar = metadata.get("avatar")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read agent metadata: {e}")

    return Agent(
        id=agent_id,
        name=name,
        path=agent_dir,
        created_at=created_at,
        avatar=avatar,
    )
