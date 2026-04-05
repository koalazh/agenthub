"""History API - Query agent evolution history from Git log.

This module provides the ability to query an Agent's evolution history
by parsing Git commit logs.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agenthub.core.config import get_config
from agenthub.core.errors import AgentHubError, NotFoundError

logger = logging.getLogger(__name__)


class EvolutionRecord(BaseModel):
    """A single evolution record from Git history."""

    evolution_id: str = Field(..., description="Unique evolution identifier")
    timestamp: datetime = Field(..., description="When the evolution occurred")
    form: str = Field(..., description="Type: 'skill' or 'experience'")
    skill_name: str | None = Field(default=None, description="Name of skill/experience")
    commit_hash: str = Field(..., description="Git commit hash")
    message: str = Field(..., description="Commit message")


class EvolutionHistoryResponse(BaseModel):
    """Paginated evolution history response."""

    records: list[EvolutionRecord] = Field(default_factory=list, description="Evolution records")
    total: int = Field(..., description="Total number of records")
    has_more: bool = Field(..., description="Whether more records exist")


# Evolution commit message pattern: Evolution-v1: +<type> <name>
_EVOLUTION_COMMIT_RE = re.compile(r"^Evolution-v1: \+(\w+) (.+)$")


async def get_evolution_history(
    agent_id: str,
    limit: int = 20,
    offset: int = 0,
) -> EvolutionHistoryResponse:
    """Get evolution history for an agent.

    Args:
        agent_id: Agent ID
        limit: Maximum number of records to return
        offset: Number of records to skip

    Returns:
        EvolutionHistoryResponse with paginated records

    Raises:
        NotFoundError: If agent does not exist
        AgentHubError: If history query fails
    """
    logger.info(f"Getting evolution history for agent '{agent_id}' (limit={limit}, offset={offset})")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id

    if not agent_dir.exists():
        raise NotFoundError(f"Agent '{agent_id}' not found")

    git_dir = agent_dir / ".git"
    if not git_dir.exists():
        raise AgentHubError(f"Agent '{agent_id}' is not a git repository")

    try:
        # Get total count
        total = _get_total_commits(git_dir)

        # Get commit log with one extra record to check has_more
        records = _get_commit_records(git_dir, limit + 1, offset)

        has_more = len(records) > limit
        if has_more:
            records = records[:limit]

        return EvolutionHistoryResponse(
            records=records,
            total=total,
            has_more=has_more,
        )

    except Exception as e:
        logger.error(f"Failed to get evolution history: {e}")
        raise AgentHubError(f"Failed to get evolution history: {e}") from e


def _get_total_commits(git_dir: Path) -> int:
    """Get total number of commits in repository.

    Args:
        git_dir: Path to .git directory

    Returns:
        Total commit count, or 0 if failed
    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(git_dir.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Failed to get total commits: {e}")
    return 0


def _get_commit_records(git_dir: Path, limit: int, offset: int) -> list[EvolutionRecord]:
    """Get evolution records from Git log.

    Args:
        git_dir: Path to .git directory
        limit: Maximum records to return
        offset: Records to skip

    Returns:
        List of EvolutionRecord
    """
    try:
        # Format: hash|timestamp|subject
        # Using short timestamp format: %ai -> ISO 8601 format
        # Note: On Windows, use -n{limit} format instead of -n={limit}
        result = subprocess.run(
            ["git", "log", f"--skip={offset}", f"-n{limit}", "--pretty=format:%H|%ai|%s"],
            cwd=str(git_dir.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(f"git log failed: {result.stderr}")
            return []

        records = []
        for line in result.stdout.strip().split("\n"):
            if not line or line.startswith('"'):
                continue

            # Parse line: hash|timestamp|subject
            parts = line.split("|")
            if len(parts) < 3:
                continue

            commit_hash = parts[0].strip('"')
            timestamp_str = parts[1].strip('"')
            subject = parts[2].strip('"')

            # Parse evolution commit message
            form, skill_name = _parse_evolution_message(subject)

            # Skip non-evolution commits (unless we want to show them)
            if form is None:
                continue

            # Parse timestamp
            try:
                # Handle formats like "2026-03-30 14:30:00 +0800"
                timestamp = datetime.strptime(timestamp_str.split(" ")[0], "%Y-%m-%d")
            except ValueError:
                timestamp = datetime.now()

            # Generate evolution_id from commit_hash (short hash)
            evolution_id = commit_hash[:8]

            records.append(EvolutionRecord(
                evolution_id=evolution_id,
                timestamp=timestamp,
                form=form,
                skill_name=skill_name,
                commit_hash=commit_hash,
                message=subject,
            ))

        return records

    except Exception as e:
        logger.warning(f"Failed to get commit records: {e}")
        return []


def _parse_evolution_message(subject: str) -> tuple[str | None, str | None]:
    """Parse evolution commit message to extract form and name.

    Args:
        subject: Commit subject line

    Returns:
        (form, skill_name) or (None, None) if not an evolution commit
    """
    match = _EVOLUTION_COMMIT_RE.match(subject)

    if match:
        form = match.group(1)  # "skill" or "experience"
        name = match.group(2).strip()
        return form, name

    return None, None
