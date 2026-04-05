"""Unit tests for core types and config."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agenthub.core.config import AgentHubConfig, get_config
from agenthub.core.errors import (
    AgentHubError,
    LLMError,
    NotFoundError,
    ParseError,
    SecurityError,
    TimeoutError,
    ValidationError,
)
from agenthub.core.types import (
    Agent,
    Change,
    EvolutionResult,
    InitAgentConfig,
    RawTranscriptInput,
    SelfEvolutionResult,
    SkillEvent,
)


class TestCoreTypes:
    """Tests for core type definitions."""

    def test_init_agent_config_validation(self):
        """Test InitAgentConfig validation."""
        config = InitAgentConfig(
            name="test-agent",
            identity="A helpful assistant",
            traits=["helpful", "friendly"],
        )
        assert config.name == "test-agent"
        assert config.identity == "A helpful assistant"
        assert config.traits == ["helpful", "friendly"]

    def test_init_agent_config_defaults(self):
        """Test InitAgentConfig default values."""
        config = InitAgentConfig(
            name="test-agent",
            identity="An assistant",
        )
        assert config.traits == []

    def test_raw_transcript_input(self):
        """Test RawTranscriptInput creation."""
        transcript = RawTranscriptInput(
            id="test-123",
            content="Hello, how are you?",
            project_id="project-1",
            metadata={"key": "value"},
        )
        assert transcript.id == "test-123"
        assert transcript.content == "Hello, how are you?"
        assert transcript.project_id == "project-1"
        assert transcript.metadata == {"key": "value"}

    def test_evolution_result(self):
        """Test EvolutionResult creation."""
        result = EvolutionResult(
            should_record=True,
            form="skill",
            scope="universal",
            skill_name="test-skill",
            content="Some skill content",
            commit_hash="abc123",
        )
        assert result.should_record is True
        assert result.form == "skill"
        assert result.scope == "universal"
        assert result.skill_name == "test-skill"

    def test_change_model(self):
        """Test Change model creation."""
        change = Change(
            type="add_skill",
            path="skills/test-skill/SKILL.md",
            content="# Test Skill",
        )
        assert change.type == "add_skill"
        assert change.path == "skills/test-skill/SKILL.md"
        assert change.content == "# Test Skill"

    def test_self_evolution_result(self):
        """Test SelfEvolutionResult creation."""
        change = Change(
            type="add_skill",
            path="skills/new-skill/SKILL.md",
            content="# New Skill",
        )
        result = SelfEvolutionResult(
            has_changes=True,
            changes=[change],
        )
        assert result.has_changes is True
        assert len(result.changes) == 1
        assert result.changes[0].type == "add_skill"

    def test_skill_event(self):
        """Test SkillEvent creation."""
        event = SkillEvent(
            type="chunk",
            content="Hello",
            tool_name="read_file",
            tool_input={"path": "test.txt"},
        )
        assert event.type == "chunk"
        assert event.content == "Hello"
        assert event.tool_name == "read_file"
        assert event.tool_input == {"path": "test.txt"}

    def test_agent_model(self):
        """Test Agent model creation."""
        agent = Agent(
            id="test-agent-123",
            name="Test Agent",
            path="/tmp/agent",
            created_at=datetime.now(timezone.utc),
        )
        assert agent.id == "test-agent-123"
        assert agent.name == "Test Agent"


class TestErrors:
    """Tests for error types."""

    def test_agenthub_error_base(self):
        """Test AgentHubError base exception."""
        error = AgentHubError("Test error", details={"key": "value"})
        assert error.message == "Test error"
        assert error.details == {"key": "value"}
        assert str(error) == "Test error"

    def test_llm_error(self):
        """Test LLMError."""
        error = LLMError("LLM failed")
        assert isinstance(error, AgentHubError)
        assert error.message == "LLM failed"

    def test_timeout_error(self):
        """Test TimeoutError."""
        error = TimeoutError("Operation timed out")
        assert isinstance(error, AgentHubError)
        assert error.message == "Operation timed out"

    def test_parse_error(self):
        """Test ParseError."""
        error = ParseError("Failed to parse response")
        assert isinstance(error, AgentHubError)
        assert error.message == "Failed to parse response"

    def test_security_error(self):
        """Test SecurityError."""
        error = SecurityError("Path traversal detected")
        assert isinstance(error, AgentHubError)
        assert error.message == "Path traversal detected"

    def test_not_found_error(self):
        """Test NotFoundError."""
        error = NotFoundError("Agent not found")
        assert isinstance(error, AgentHubError)
        assert error.message == "Agent not found"

    def test_validation_error(self):
        """Test ValidationError."""
        error = ValidationError("Invalid config")
        assert isinstance(error, AgentHubError)
        assert error.message == "Invalid config"


class TestConfig:
    """Tests for configuration."""

    def test_get_config_returns_singleton(self):
        """Test that get_config returns the same instance."""
        config1 = get_config()
        config2 = get_config()
        assert config1 is config2

    def test_config_default_values(self):
        """Test AgentHubConfig default values."""
        config = AgentHubConfig()
        assert config.agenthub_dir.name == ".agenthub"
        assert config.default_timeout == 120
        assert config.evolution_timeout == 180
        assert config.self_evolution_timeout == 300
        assert config.init_agent_timeout == 120

    def test_config_ensure_dirs(self, tmp_path):
        """Test that ensure_dirs creates required directories."""
        config = AgentHubConfig(agenthub_dir=tmp_path / ".agenthub")
        config.ensure_dirs()
        assert config.agenthub_dir.exists()
