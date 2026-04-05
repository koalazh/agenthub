"""Evolution API - Per-agent perspective."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from agenthub.core.config import get_config
from agenthub.core.errors import AgentHubError
from agenthub.core.lock import GitLock
from agenthub.core.types import EvolutionResult, RawTranscriptInput, SkillEvent
from agenthub.runtime.executor import get_executor, parse_evolution_result

logger = logging.getLogger(__name__)


async def evolution(
    agent_id: str,
    raw_input: RawTranscriptInput,
) -> EvolutionResult:
    """Analyze a transcript and decide if experiences should be recorded.

    This function:
    1. Acquires git lock for the agent
    2. Archives the transcript to the agent's archives directory
    3. Creates a deep agent with the evolution skill (agent scope - sees only own directory)
    4. Analyzes the transcript using progressive disclosure
    5. Releases git lock

    Args:
        agent_id: ID of the agent to perform evolution for
        raw_input: Raw transcript input to analyze

    Returns:
        EvolutionResult with the decision
    """
    logger.info(f"Running evolution for agent '{agent_id}'")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id

    if not agent_dir.exists():
        raise AgentHubError(f"Agent '{agent_id}' not found")

    # Use git lock to prevent concurrent evolution operations
    lock_path = agent_dir / ".git" / "agenthub.lock"

    try:
        with GitLock(lock_path).hold():
            # Archive the transcript
            archive_path = _archive_transcript(agent_id, raw_input, config.agenthub_dir)

            # Execute evolution skill (agent scope - sees only own directory)
            executor = get_executor()

            # API层仅传递目录路径，扫描由Skill层自主执行
            skills_dir = agent_dir / "skills"
            memory_dir = agent_dir / "memory"

            result = await executor.execute(
                skill_name="evolution",
                task_description="Analyze the transcript and decide what experiences should be recorded as Skills or Experiences.",
                agent_id=agent_id,
                context={
                    "archive_path": str(archive_path),
                    "transcript_id": raw_input.id,
                    "project_id": raw_input.project_id or "universal",
                    "skills_dir": str(skills_dir),
                    "memory_dir": str(memory_dir),
                },
                timeout=config.evolution_timeout,
                scope="agent",
            )

            # Parse and return result
            return parse_evolution_result(result)

    except TimeoutError:
        logger.error("Evolution timed out waiting for lock")
        raise AgentHubError("Evolution timed out - another evolution may be in progress") from None
    except Exception as e:
        logger.error(f"Evolution failed: {e}")
        raise AgentHubError(f"Evolution failed: {e}") from e


async def evolution_stream(
    agent_id: str,
    raw_input: RawTranscriptInput,
) -> AsyncIterator[SkillEvent]:
    """Streaming version of evolution for real-time display.

    Args:
        agent_id: ID of the agent
        raw_input: Raw transcript input

    Yields:
        SkillEvent objects for streaming
    """
    logger.info(f"Running evolution (streaming) for agent '{agent_id}'")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id
    lock_path = agent_dir / ".git" / "agenthub.lock"

    try:
        with GitLock(lock_path).hold():
            archive_path = _archive_transcript(agent_id, raw_input, config.agenthub_dir)

            # API层仅传递目录路径，扫描由Skill层自主执行
            skills_dir = agent_dir / "skills"
            memory_dir = agent_dir / "memory"

            executor = get_executor()

            async for event in executor.execute_stream(
                skill_name="evolution",
                task_description="Analyze the transcript and decide what experiences should be recorded.",
                agent_id=agent_id,
                context={
                    "archive_path": str(archive_path),
                    "transcript_id": raw_input.id,
                    "project_id": raw_input.project_id or "universal",
                    "skills_dir": str(skills_dir),
                    "memory_dir": str(memory_dir),
                },
                timeout=config.evolution_timeout,
                scope="agent",
            ):
                yield event

    except TimeoutError:
        logger.error("Evolution streaming timed out waiting for lock")
        yield SkillEvent(type="error", content="Evolution timed out - another evolution may be in progress")
    except Exception as e:
        logger.error(f"Evolution streaming failed: {e}")
        yield SkillEvent(type="error", content=str(e))


def _archive_transcript(
    agent_id: str,
    raw_input: RawTranscriptInput,
    agenthub_dir: Path,
) -> Path:
    """Archive a transcript to the agent's archives directory.

    Args:
        agent_id: Agent ID
        raw_input: Transcript to archive
        agenthub_dir: AgentHub root directory

    Returns:
        Path to the archived transcript
    """
    archives_dir = agenthub_dir / agent_id / "archives"
    archives_dir.mkdir(parents=True, exist_ok=True)

    # Create archive filename with timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_filename = f"{raw_input.id}_{timestamp}.json"
    archive_path = archives_dir / archive_filename

    # Write archive
    archive_data = {
        "id": raw_input.id,
        "content": raw_input.content,
        "project_id": raw_input.project_id,
        "metadata": raw_input.metadata or {},
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }

    archive_path.write_text(json.dumps(archive_data, indent=2), encoding="utf-8")

    logger.info(f"Archived transcript to {archive_path}")

    return archive_path
