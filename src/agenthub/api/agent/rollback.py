"""Rollback API - Git reset to previous commit.

This module provides the ability to rollback an Agent's configuration
to a previous commit in the Git history.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from agenthub.core.config import get_config
from agenthub.core.errors import AgentHubError, NotFoundError
from agenthub.core.lock import GitLock

logger = logging.getLogger(__name__)


class RollbackRequest(BaseModel):
    """Request to rollback agent to a previous commit."""

    agent_id: str = Field(..., description="Agent ID")
    target: str = Field(..., description="Target: 'HEAD~N' or commit hash")

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: str) -> str:
        """Validate target format.

        Args:
            v: Target string

        Returns:
            Validated target

        Raises:
            ValueError: If target format is invalid
        """
        # Check for HEAD~N pattern
        head_pattern = re.compile(r"^HEAD~(\d+)$")
        match = head_pattern.match(v)
        if match:
            n = int(match.group(1))
            if n > 10:
                raise ValueError("HEAD~N with N > 10 is not allowed")
            if n < 1:
                raise ValueError("HEAD~N with N < 1 is not valid")
            return v

        # Check for commit hash pattern (40 hex characters or short hash)
        hash_pattern = re.compile(r"^[0-9a-f]{4,40}$", re.IGNORECASE)
        if not hash_pattern.match(v):
            raise ValueError("Target must be 'HEAD~N' or a valid commit hash")

        return v


class RollbackResponse(BaseModel):
    """Response from rollback operation."""

    success: bool = Field(..., description="Whether rollback succeeded")
    previous_commit: str = Field(..., description="Commit before rollback")
    new_commit: str = Field(..., description="Commit after rollback")
    warning: str | None = Field(default=None, description="Warning message if any")


async def rollback_agent(request: RollbackRequest) -> RollbackResponse:
    """Rollback an agent to a previous commit.

    Args:
        request: Rollback request with agent_id and target

    Returns:
        RollbackResponse with operation result

    Raises:
        NotFoundError: If agent does not exist
        AgentHubError: If rollback fails
    """
    logger.info(f"Rolling back agent '{request.agent_id}' to '{request.target}'")

    config = get_config()
    agent_dir = config.agenthub_dir / request.agent_id

    if not agent_dir.exists():
        raise NotFoundError(f"Agent '{request.agent_id}' not found")

    git_dir = agent_dir / ".git"
    if not git_dir.exists():
        raise AgentHubError(f"Agent '{request.agent_id}' is not a git repository")

    lock_path = git_dir / "agenthub.lock"

    try:
        with GitLock(lock_path).hold():
            # Get current HEAD before rollback
            previous_commit = _get_current_commit(git_dir)
            if previous_commit is None:
                raise AgentHubError("Git operation failed: unable to get current commit")

            # Resolve target to actual commit hash
            resolved_target = _resolve_target(git_dir, request.target)

            # Check if target is the same as current HEAD
            if resolved_target == previous_commit:
                raise AgentHubError("Already at target")

            # Execute git reset --hard
            success = _git_reset_hard(git_dir, resolved_target)
            if not success:
                raise AgentHubError("Git operation failed: reset --hard failed")

            # Get new HEAD
            new_commit = _get_current_commit(git_dir)
            if new_commit is None:
                new_commit = "0000000"

            return RollbackResponse(
                success=True,
                previous_commit=previous_commit,
                new_commit=new_commit,
                warning=None,
            )

    except TimeoutError:
        logger.error("Rollback timed out waiting for lock")
        raise AgentHubError("Rollback timed out - another operation may be in progress") from None
    except AgentHubError:
        raise
    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        raise AgentHubError(f"Rollback failed: {e}") from e


def _get_current_commit(git_dir: Path) -> str | None:
    """Get current HEAD commit hash.

    Args:
        git_dir: Path to .git directory

    Returns:
        Current commit hash or None if failed
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(git_dir.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Failed to get current commit: {e}")
    return None


def _resolve_target(git_dir: Path, target: str) -> str:
    """Resolve target (HEAD~N or hash) to actual commit hash.

    Args:
        git_dir: Path to .git directory
        target: Target string (HEAD~N or commit hash)

    Returns:
        Resolved commit hash

    Raises:
        AgentHubError: If target is invalid
    """
    try:
        # Handle HEAD~N pattern - git rev-parse handles HEAD~N directly
        ref = target  # Use original target, git understands HEAD~1, HEAD~2, etc.

        result = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=str(git_dir.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            commit_hash = result.stdout.strip()
            logger.info(f"Resolved target '{target}' to '{commit_hash}'")
            return commit_hash

        # If simple resolution failed, try original target as hash
        result = subprocess.run(
            ["git", "rev-parse", "--verify", target],
            cwd=str(git_dir.parent),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        raise AgentHubError(f"Invalid commit target: {target}")

    except subprocess.TimeoutExpired:
        raise AgentHubError("Git operation timed out during target resolution")
    except AgentHubError:
        raise
    except Exception as e:
        raise AgentHubError(f"Failed to resolve target: {e}") from e


def _git_reset_hard(git_dir: Path, target: str) -> bool:
    """Execute git reset --hard to target.

    Args:
        git_dir: Path to .git directory
        target: Target commit hash

    Returns:
        True if successful, False otherwise
    """
    try:
        result = subprocess.run(
            ["git", "reset", "--hard", target],
            cwd=str(git_dir.parent),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"git reset --hard failed: {result.stderr}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("git reset --hard timed out")
        return False
    except Exception as e:
        logger.error(f"git reset --hard failed: {e}")
        return False
