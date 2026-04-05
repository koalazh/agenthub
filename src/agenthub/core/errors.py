"""Error types for AgentHub."""

from __future__ import annotations

from typing import Any


class AgentHubError(Exception):
    """Base exception for all AgentHub errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class LLMError(AgentHubError):
    """Raised when an LLM API call fails."""

    pass


class TimeoutError(AgentHubError):
    """Raised when an operation times out."""

    pass


class ParseError(AgentHubError):
    """Raised when parsing an LLM response fails."""

    pass


class SecurityError(AgentHubError):
    """Raised for security violations (path traversal, dangerous commands, etc.)."""

    pass


class NotFoundError(AgentHubError):
    """Raised when a requested resource is not found."""

    pass


class ValidationError(AgentHubError):
    """Raised when input validation fails."""

    pass


class BackendError(AgentHubError):
    """Raised when a backend operation fails."""

    pass


class SkillError(AgentHubError):
    """Raised when a skill operation fails."""

    pass


class PruneProtectedError(AgentHubError):
    """Raised when attempting to prune a protected file."""

    pass


class IndexConstraintExceededError(AgentHubError):
    """Raised when MEMORY.md exceeds quantitative constraints (200 lines/25KB)."""

    pass


class InvalidExperienceTypeError(AgentHubError):
    """Raised when experience_type field has an invalid value."""

    pass


class PathTraversalAttemptError(SecurityError):
    """Raised when a path traversal attempt is detected."""

    pass


class MigrationInProgressError(AgentHubError):
    """Raised when data migration is in progress."""

    pass
