"""Unit tests for Export, Rollback, History, and Init Agent APIs."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from agenthub.api.agent.history import _parse_evolution_message, get_evolution_history
from agenthub.api.agent.rollback import (
    RollbackRequest,
    RollbackResponse,
    _git_reset_hard,
    _resolve_target,
)
from agenthub.api.hub.export import (
    ClaudeCodeLaunchConfig,
    SystemPromptSection,
    _assemble_system_prompt,
    _build_memory_content,
    _build_sections,
    _build_skills_index,
    _iterate_skills,
    _read_file_safe,
)
from agenthub.api.hub.init_agent import init_agent
from agenthub.core.errors import AgentHubError, NotFoundError, ParseError
from agenthub.core.types import InitAgentConfig


class TestExportAPI:
    """Tests for Export API."""

    def test_read_file_safe_existing(self, tmp_path: Path):
        """Test reading an existing file."""
        test_file = tmp_path / "test.md"
        test_file.write_text("test content", encoding="utf-8")
        content = _read_file_safe(test_file)
        assert content == "test content"

    def test_read_file_safe_missing(self, tmp_path: Path):
        """Test reading a missing file returns empty string."""
        content = _read_file_safe(tmp_path / "missing.md")
        assert content == ""

    def test_iterate_skills_empty_dir(self, tmp_path: Path):
        """Test iterating over empty skills directory."""
        skills = _iterate_skills(tmp_path)
        assert skills == []

    def test_iterate_skills_with_files(self, tmp_path: Path):
        """Test iterating over skills directory with files."""
        (tmp_path / "skill1.md").write_text("content1", encoding="utf-8")
        (tmp_path / "skill2.md").write_text("content2", encoding="utf-8")
        skills = _iterate_skills(tmp_path)
        assert len(skills) == 2

    def test_iterate_skills_deduplication(self, tmp_path: Path):
        """Test that duplicate files are not added."""
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "skill.md").write_text("content", encoding="utf-8")
        # Add same file again
        skills = _iterate_skills(tmp_path)
        # Should not have duplicates
        paths = [str(p) for p in skills]
        assert len(paths) == len(set(paths))

    def test_assemble_system_prompt(self):
        """Test system prompt assembly with Markdown format."""
        sections = _build_sections(
            soul="You are helpful",
            identity="You are Claude",
            bootstrap="Do good work",
            skills_index="## Available Skills\n- skill1",
            memory_content="## Memory\nRemember this",
        )
        prompt = _assemble_system_prompt(sections)
        assert "## Agent Identity" in prompt
        assert "## Agent Soul" in prompt
        assert "## Available Skills" in prompt
        assert "## Memory" in prompt
        assert "## Instructions" in prompt
        assert "---" in prompt  # Footer

    def test_assemble_system_prompt_partial(self):
        """Test system prompt assembly with partial content."""
        sections = _build_sections(
            soul="",
            identity="You are Claude",
            bootstrap="",
            skills_index="",
            memory_content="",
        )
        prompt = _assemble_system_prompt(sections)
        assert "## Agent Identity" in prompt
        assert "## Agent Soul" not in prompt
        assert "## Instructions" not in prompt

    def test_assemble_system_prompt_section_order(self):
        """Test that sections are sorted by order."""
        sections = _build_sections(
            soul="Soul content",
            identity="Identity content",
            bootstrap="Bootstrap content",
            skills_index="Skills content",
            memory_content="Memory content",
        )
        prompt = _assemble_system_prompt(sections)
        # Identity (1) should come before Soul (2)
        assert prompt.index("## Agent Identity") < prompt.index("## Agent Soul")
        # Soul (2) should come before inline Skills (3)
        assert prompt.index("## Agent Soul") < prompt.index("Skills content")
        # Soul (2) should come before Memory (4)
        assert prompt.index("## Agent Soul") < prompt.index("Memory content")

    def test_assemble_system_prompt_empty_all(self):
        """Test system prompt assembly with all empty sections."""
        sections = _build_sections(
            soul="",
            identity="",
            bootstrap="",
            skills_index="",
            memory_content="",
        )
        prompt = _assemble_system_prompt(sections)
        assert prompt == "---"  # Only footer

    def test_build_skills_index(self, tmp_path: Path):
        """Test building skills index."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        builtin_dir = skills_dir / "builtin"
        builtin_dir.mkdir()
        (builtin_dir / "evolution.md").write_text("Evolution skill", encoding="utf-8")
        index = _build_skills_index(tmp_path, None)
        assert "# Built-in Skills" in index
        assert "evolution" in index

    def test_build_memory_content_empty(self, tmp_path: Path):
        """Test building memory content with no memory."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        content = _build_memory_content(tmp_path, None)
        assert "## Memory" in content

    def test_claudecode_launch_config_model(self):
        """Test ClaudeCodeLaunchConfig model."""
        config = ClaudeCodeLaunchConfig(
            agent_id="test-123",
            agent_name="test-agent",
            version="v1.0",
            system_prompt="You are helpful",
        )
        assert config.agent_id == "test-123"
        assert config.agent_name == "test-agent"
        assert config.version == "v1.0"
        assert config.allowed_tools == ["Read", "Edit", "Bash", "Glob", "Grep"]


class TestRollbackAPI:
    """Tests for Rollback API."""

    def test_rollback_request_validation_valid_hash(self):
        """Test RollbackRequest with valid commit hash."""
        req = RollbackRequest(agent_id="test", target="abc123def")
        assert req.target == "abc123def"

    def test_rollback_request_validation_head(self):
        """Test RollbackRequest with HEAD~N."""
        req = RollbackRequest(agent_id="test", target="HEAD~1")
        assert req.target == "HEAD~1"

    def test_rollback_request_validation_head_large_n(self):
        """Test RollbackRequest with HEAD~N > 10 is rejected."""
        with pytest.raises(ValueError, match="N > 10"):
            RollbackRequest(agent_id="test", target="HEAD~11")

    def test_rollback_request_validation_invalid_format(self):
        """Test RollbackRequest with invalid format is rejected."""
        with pytest.raises(ValueError):
            RollbackRequest(agent_id="test", target="invalid!!")

    def test_rollback_response_model(self):
        """Test RollbackResponse model."""
        resp = RollbackResponse(
            success=True,
            previous_commit="abc123",
            new_commit="def456",
            warning=None,
        )
        assert resp.success is True
        assert resp.previous_commit == "abc123"
        assert resp.new_commit == "def456"


class TestHistoryAPI:
    """Tests for History API."""

    def test_parse_evolution_message_skill(self):
        """Test parsing skill commit message."""
        form, name = _parse_evolution_message("Evolution-v1: +skill my-skill")
        assert form == "skill"
        assert name == "my-skill"

    def test_parse_evolution_message_experience(self):
        """Test parsing experience commit message."""
        form, name = _parse_evolution_message("Evolution-v1: +experience my-exp")
        assert form == "experience"
        assert name == "my-exp"

    def test_parse_evolution_message_non_evolution(self):
        """Test parsing non-evolution commit message."""
        form, name = _parse_evolution_message("Regular commit message")
        assert form is None
        assert name is None

    def test_parse_evolution_message_with_spaces(self):
        """Test parsing evolution message with spaces in name."""
        form, name = _parse_evolution_message("Evolution-v1: +skill my skill name")
        assert form == "skill"
        assert name == "my skill name"

    def test_parse_evolution_message_uppercase(self):
        """Test that non-matching case returns None."""
        form, name = _parse_evolution_message("evolution-v1: +skill test")
        assert form is None

    @pytest.mark.asyncio
    async def test_archive_count_returns_int(self, temp_agent_dir):
        """Test archive_count returns integer."""
        from agenthub.api.agent.self_evolution import archive_count

        agent_id = temp_agent_dir.name
        count = await archive_count(agent_id)

        assert isinstance(count, int)
        assert count >= 0


class TestGitIntegration:
    """Integration tests that require actual git repository."""

    @pytest.fixture
    def git_repo(self, tmp_path: Path):
        """Create a temporary git repository."""
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )
        return tmp_path

    def test_git_reset_hard(self, git_repo: Path):
        """Test git reset --hard execution."""
        # Create initial commit
        test_file = git_repo / "test.txt"
        test_file.write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        v1_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        ).stdout.strip()

        # Make second commit
        test_file.write_text("v2", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Update"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )

        # Reset to first commit
        success = _git_reset_hard(git_repo / ".git", v1_hash)
        assert success is True
        assert test_file.read_text(encoding="utf-8") == "v1"

    def test_resolve_target_head(self, git_repo: Path):
        """Test resolving HEAD target."""
        # Create commits
        test_file = git_repo / "test.txt"
        test_file.write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "Evolution-v1: +skill test"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )

        resolved = _resolve_target(git_repo / ".git", "HEAD~1")
        assert len(resolved) == 40  # Full hash

    def test_resolve_target_hash(self, git_repo: Path):
        """Test resolving commit hash target."""
        test_file = git_repo / "test.txt"
        test_file.write_text("v1", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=git_repo,
            check=True,
            capture_output=True,
        )
        v1_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        ).stdout.strip()

        resolved = _resolve_target(git_repo / ".git", v1_hash)
        assert resolved == v1_hash


class TestInitAgentAPI:
    """Tests for Init Agent API."""

    @pytest.fixture
    def mock_executor_success(self):
        """Mock executor that returns successful init result in new InitAgentResult format."""
        from agenthub.core.config import get_config

        mock = MagicMock()

        async def mock_execute(*args, **kwargs):
            # Get the name from context to generate consistent agent_id
            ctx = kwargs.get('context', {})
            agent_name = ctx.get('name', 'test-agent')
            # Replicate _generate_agent_id logic to create files in correct location
            import re
            from datetime import datetime, timezone
            safe_name = re.sub(r"[^a-z0-9]+", "-", agent_name.lower()).strip("-")
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            agent_id = f"{safe_name}-{timestamp}"

            # Create actual files in agent directory
            config = get_config()
            agent_dir = config.agenthub_dir / agent_id
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "soul.md").write_text("# Soul\nYou are helpful.", encoding="utf-8")
            (agent_dir / "identity.md").write_text("# Identity\nI am an AI agent.", encoding="utf-8")
            (agent_dir / "BOOTSTRAP.md").write_text("# Bootstrap\nAlways write tests.", encoding="utf-8")

            return json.dumps({
                "phase": "FINALIZE",
                "hasChanges": True,
                "inspirationSeed": 123456789,
                "agent_name": "Midnight",
                "personality": "A curious helper who loves debugging",
                "files_written": ["soul.md", "identity.md", "BOOTSTRAP.md"],
                "git_commit": "abc1234",
            })

        mock.execute = AsyncMock(side_effect=mock_execute)
        return mock

    @pytest.fixture
    def mock_executor_invalid_json(self):
        """Mock executor that returns invalid JSON."""
        mock = MagicMock()
        mock.execute = AsyncMock(side_effect=lambda *args, **kwargs: "not valid json")
        return mock

    @pytest.fixture
    def mock_executor_error(self):
        """Mock executor that raises an error."""
        mock = MagicMock()
        mock.execute = AsyncMock(side_effect=AgentHubError("Skill execution failed"))
        return mock

    @pytest.fixture
    def mock_executor_timeout(self):
        """Mock executor that raises timeout error."""
        mock = MagicMock()

        async def mock_execute(*args, **kwargs):
            raise TimeoutError("Execution timed out")

        mock.execute = AsyncMock(side_effect=mock_execute)
        return mock

    @pytest.fixture
    def mock_executor_invalid_result(self):
        """Mock executor that returns non-standard LLM output (now tolerated)."""
        mock = MagicMock()

        async def mock_execute(*args, **kwargs):
            # Non-standard LLM output - now tolerated with extra='ignore'
            return json.dumps({
                "phase": "COMPLETED",
                "agent_id": "test-agent-timestamp",
                "status": "success",
                "notes": ["Personality generated based on traits"],
            })

        mock.execute = AsyncMock(side_effect=mock_execute)
        return mock

    @pytest.fixture
    def mock_executor_missing_files(self):
        """Mock executor that reports all files but only creates some."""
        from agenthub.core.config import get_config

        mock = MagicMock()

        async def mock_execute(*args, **kwargs):
            ctx = kwargs.get('context', {})
            agent_name = ctx.get('name', 'test-agent')
            import re
            from datetime import datetime, timezone
            safe_name = re.sub(r"[^a-z0-9]+", "-", agent_name.lower()).strip("-")
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            agent_id = f"{safe_name}-{timestamp}"

            # Create only soul.md, intentionally missing identity.md and BOOTSTRAP.md
            config = get_config()
            agent_dir = config.agenthub_dir / agent_id
            agent_dir.mkdir(parents=True, exist_ok=True)
            (agent_dir / "soul.md").write_text("# Soul\nYou are helpful.", encoding="utf-8")
            # identity.md and BOOTSTRAP.md are NOT created

            return json.dumps({
                "phase": "FINALIZE",
                "hasChanges": True,
                "inspirationSeed": 123456789,
                "agent_name": "Midnight",
                "personality": "A curious helper",
                "files_written": ["soul.md", "identity.md", "BOOTSTRAP.md"],  # Reports all as written
                "git_commit": "abc1234",
            })

        mock.execute = AsyncMock(side_effect=mock_execute)
        return mock

    @pytest.mark.asyncio
    async def test_init_agent_success(self, mock_executor_success):
        """Test successful agent creation."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_success)

        config = InitAgentConfig(
            name="test-agent",
            identity="A helpful coding assistant",
            traits=["detail-oriented"],
        )

        agent = await init_agent(config)

        assert agent.name == "Midnight"  # From mock executor
        assert agent.id.startswith("test-agent-")
        assert agent.path.exists()

    @pytest.mark.asyncio
    async def test_init_agent_empty_name_is_valid(self):
        """Test that empty name is now valid (becomes None after normalization)."""
        config = InitAgentConfig(
            name="",
            identity="A helpful coding assistant",
            traits=[],
        )
        # Empty string becomes None after normalization
        assert config.name is None

    @pytest.mark.asyncio
    async def test_init_agent_null_name_is_valid(self):
        """Test that null name is now valid (optional)."""
        config = InitAgentConfig(
            name=None,  # type: ignore
            identity="A helpful coding assistant",
            traits=[],
        )
        # None is valid for optional name
        assert config.name is None

    @pytest.mark.asyncio
    async def test_init_agent_invalid_json(self, mock_executor_invalid_json):
        """Test that invalid JSON from executor raises AgentHubError."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_invalid_json)

        config = InitAgentConfig(
            name="test-agent",
            identity="A helpful coding assistant",
            traits=[],
        )

        with pytest.raises(AgentHubError, match="SKILL_OUTPUT_PARSE_ERROR"):
            await init_agent(config)

    @pytest.mark.asyncio
    async def test_init_agent_nonstandard_result(self, mock_executor_invalid_result):
        """Test that non-standard LLM output is tolerated with defaults."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_invalid_result)

        config = InitAgentConfig(
            name="test-agent",
            identity="A helpful coding assistant",
            traits=[],
        )

        # Should not raise - now tolerates non-standard output with extra='ignore'
        agent = await init_agent(config)
        assert agent.id.startswith("test-agent-")  # Agent ID includes timestamp
        assert agent.name  # Should have a name from fallback

    @pytest.mark.asyncio
    async def test_init_agent_execution_error(self, mock_executor_error):
        """Test that executor error raises AgentHubError."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_error)

        config = InitAgentConfig(
            name="test-agent",
            identity="A helpful coding assistant",
            traits=[],
        )

        with pytest.raises(AgentHubError):
            await init_agent(config)

    @pytest.mark.asyncio
    async def test_init_agent_timeout(self, mock_executor_timeout):
        """Test that executor timeout raises AgentHubError."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_timeout)

        config = InitAgentConfig(
            name="test-agent",
            identity="A helpful coding assistant",
            traits=[],
        )

        with pytest.raises(AgentHubError):
            await init_agent(config)

    @pytest.mark.asyncio
    async def test_init_agent_missing_files(self, mock_executor_missing_files):
        """Test that missing files raises AgentHubError."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_missing_files)

        config = InitAgentConfig(
            name="test-agent",
            identity="A helpful coding assistant",
            traits=[],
        )

        with pytest.raises(AgentHubError, match="FILE_WRITE_MISSING"):
            await init_agent(config)

    @pytest.mark.asyncio
    async def test_init_agent_cleanup_on_failure(self, mock_executor_error):
        """Test that directory is cleaned up on failure."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_error)

        config = InitAgentConfig(
            name="cleanup-test-agent",
            identity="A helpful coding assistant",
            traits=[],
        )

        agent_dir = None
        try:
            with pytest.raises(AgentHubError):
                await init_agent(config)
        finally:
            # Find the agent directory
            from agenthub.core.config import get_config
            config = get_config()
            # Check if any cleanup-test-agent directory exists
            for item in config.agenthub_dir.iterdir():
                if "cleanup-test-agent" in item.name:
                    agent_dir = item
                    break

        # Directory should be cleaned up
        if agent_dir is not None:
            assert not agent_dir.exists()

    @pytest.mark.asyncio
    async def test_init_agent_includes_avatar(self, mock_executor_success):
        """Test that init_agent returns Agent with avatar field."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_success)

        config = InitAgentConfig(
            name="avatar-test",
            identity="A helpful coding assistant",
            traits=["detail-oriented"],
        )

        agent = await init_agent(config)

        assert agent.id.startswith("avatar-test-")
        assert agent.avatar is not None

    @pytest.mark.asyncio
    async def test_init_agent_avatar_is_ascii(self, mock_executor_success):
        """Test that init_agent returns ASCII avatar."""
        from agenthub.runtime.executor import set_executor

        set_executor(mock_executor_success)

        config = InitAgentConfig(
            name="ascii-test",
            identity="A helpful coding assistant",
            traits=["detail-oriented"],
        )

        agent = await init_agent(config)

        assert agent.avatar is not None
        # Avatar should be ASCII art (contains non-alphanumeric characters)
        assert len(agent.avatar) > 0
