"""Delete Agent API."""

from __future__ import annotations

import logging
import shutil

from agenthub.core.config import get_config
from agenthub.core.errors import NotFoundError

logger = logging.getLogger(__name__)


async def delete_agent(agent_id: str) -> None:
    """Delete an agent and all its data.

    Args:
        agent_id: ID of the agent to delete

    Raises:
        NotFoundError: If agent is not found
    """
    logger.info(f"Deleting agent: {agent_id}")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id

    if not agent_dir.exists():
        raise NotFoundError(f"Agent '{agent_id}' not found")

    try:
        # Remove agent directory
        shutil.rmtree(agent_dir)
        logger.info(f"Successfully deleted agent '{agent_id}'")
    except Exception as e:
        logger.error(f"Failed to delete agent '{agent_id}': {e}")
        raise
