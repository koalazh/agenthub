"""Self Evolution API - Per-agent perspective."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import AsyncIterator

from agenthub.core.config import get_config
from agenthub.core.errors import AgentHubError
from agenthub.core.lock import GitLock
from agenthub.core.types import SelfEvolutionResult, SkillEvent
from agenthub.runtime.executor import get_executor, parse_self_evolution_result

logger = logging.getLogger(__name__)


async def self_evolution(agent_id: str) -> SelfEvolutionResult:
    """Perform self-evolution by analyzing accumulated archives.

    This function:
    1. Acquires git lock for the agent
    2. Reads all archives from the agent's archives directory
    3. Analyzes patterns across all transcripts
    4. Identifies gaps in existing skills
    5. Creates new skills or experiences as needed
    6. Returns the changes made

    Args:
        agent_id: ID of the agent to self-evolve

    Returns:
        SelfEvolutionResult with changes made
    """
    logger.info(f"Running self-evolution for agent '{agent_id}'")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id

    if not agent_dir.exists():
        raise AgentHubError(f"Agent '{agent_id}' not found")

    archives_dir = agent_dir / "archives"
    if not archives_dir.exists():
        logger.info(f"No archives found for agent '{agent_id}', skipping self-evolution")
        return SelfEvolutionResult(has_changes=False, changes=[])

    # Use git lock to prevent concurrent operations
    lock_path = agent_dir / ".git" / "agenthub.lock"

    try:
        with GitLock(lock_path).hold():
            # API层仅传递目录路径，扫描由Skill层自主执行
            skills_dir = agent_dir / "skills"
            memory_dir = agent_dir / "memory"

            # Execute self-evolution skill (agent scope - sees only own directory)
            executor = get_executor()

            result = await executor.execute(
                skill_name="self-evolution",
                task_description="Review past archives to find gaps - what important information was recorded as experience but should have been a skill, or what was missed entirely.",
                agent_id=agent_id,
                context={
                    "archives_dir": str(archives_dir),
                    "skills_dir": str(skills_dir),
                    "memory_dir": str(memory_dir),
                },
                timeout=config.self_evolution_timeout,
                scope="agent",
            )

            # Parse and return result
            result_obj = parse_self_evolution_result(result)

            # Write self-evolution marker
            marker_path = agent_dir / ".last_self_evolution"
            marker_path.write_text(str(time.time()))
            return result_obj

    except TimeoutError:
        logger.error("Self-evolution timed out waiting for lock")
        raise AgentHubError("Self-evolution timed out - another operation may be in progress") from None
    except Exception as e:
        logger.error(f"Self-evolution failed: {e}")
        raise AgentHubError(f"Self-evolution failed: {e}") from e


async def archive_count(agent_id: str) -> int:
    """Get the count of archives since last self-evolution.

    This function:
    1. Reads the last self-evolution timestamp marker
    2. Counts archives created after that timestamp
    3. If no marker exists, counts all archives

    Args:
        agent_id: ID of the agent

    Returns:
        Number of archives since last self-evolution
    """
    logger.info(f"Getting archive count for agent '{agent_id}'")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id

    if not agent_dir.exists():
        raise AgentHubError(f"Agent '{agent_id}' not found")

    archives_dir = agent_dir / "archives"
    if not archives_dir.exists():
        return 0

    # Check for last self-evolution marker
    marker_path = agent_dir / ".last_self_evolution"
    last_ts: float | None = None
    if marker_path.exists():
        try:
            last_ts = float(marker_path.read_text().strip())
        except (ValueError, OSError):
            last_ts = None

    # Count archives
    count = 0
    for archive_file in archives_dir.iterdir():
        if archive_file.is_file() and archive_file.suffix == ".json":
            if last_ts is None:
                count += 1
            else:
                # Only count if newer than last self-evolution
                try:
                    mtime = archive_file.stat().st_mtime
                    if mtime > last_ts:
                        count += 1
                except OSError:
                    pass

    return count


async def self_evolution_stream(agent_id: str) -> AsyncIterator[SkillEvent]:
    """Streaming version of self-evolution.

    Args:
        agent_id: ID of the agent

    Yields:
        SkillEvent objects for streaming
    """
    logger.info(f"Running self-evolution (streaming) for agent '{agent_id}'")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id
    archives_dir = agent_dir / "archives"
    lock_path = agent_dir / ".git" / "agenthub.lock"

    # Match the sync version: skip if no archives
    if not archives_dir.exists():
        logger.info(f"No archives found for agent '{agent_id}', skipping self-evolution")
        yield SkillEvent(type="done", content="No archives to review")
        return

    try:
        with GitLock(lock_path).hold():
            # API层仅传递目录路径，扫描由Skill层自主执行
            skills_dir = agent_dir / "skills"
            memory_dir = agent_dir / "memory"

            executor = get_executor()

            async for event in executor.execute_stream(
                skill_name="self-evolution",
                task_description="Review past archives to find gaps - what important information was recorded as experience but should have been a skill, or what was missed entirely.",
                agent_id=agent_id,
                context={
                    "archives_dir": str(archives_dir),
                    "skills_dir": str(skills_dir),
                    "memory_dir": str(memory_dir),
                },
                timeout=config.self_evolution_timeout,
                scope="agent",
            ):
                yield event

    except TimeoutError:
        logger.error("Self-evolution streaming timed out waiting for lock")
        yield SkillEvent(type="error", content="Self-evolution timed out - another operation may be in progress")
    except Exception as e:
        logger.error(f"Self-evolution streaming failed: {e}")
        yield SkillEvent(type="error", content=str(e))
