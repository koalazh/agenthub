"""Unit tests for the backend module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenthub.backend.agenthub_backend import AgentHubBackend, create_agent_backend


class TestAgentHubBackend:
    """Tests for AgentHubBackend."""

    def test_backend_initialization(self, tmp_path):
        """Test backend initialization with custom directory."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
            root_dir=tmp_path / ".agenthub" / "test-agent",
        )
        assert backend.agent_id == "test-agent"
        assert backend.virtual_mode is True

    def test_backend_id_property(self, tmp_path):
        """Test backend id property."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        assert backend.id == "agenthub-test-agent"

    def test_backend_id_without_agent_id(self, tmp_path):
        """Test backend id property without agent_id."""
        backend = AgentHubBackend(agenthub_dir=tmp_path / ".agenthub")
        assert backend.id == "agenthub-unknown"

    def test_validate_git_command_valid(self, tmp_path):
        """Test _validate_git_command with valid git status."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        result = backend._validate_git_command("git status")
        assert result is None  # None means valid

    def test_validate_git_command_valid_add(self, tmp_path):
        """Test _validate_git_command with valid git add."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        result = backend._validate_git_command("git add file.txt")
        assert result is None

    def test_validate_git_command_valid_commit(self, tmp_path):
        """Test _validate_git_command with valid git commit."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        result = backend._validate_git_command("git commit -m 'test message'")
        assert result is None

    def test_validate_git_command_invalid_subcommand(self, tmp_path):
        """Test _validate_git_command with invalid subcommand."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        result = backend._validate_git_command("git rm -rf /")
        assert result is not None
        assert result.exit_code == 1
        assert "[ERROR]" in result.output
        assert "git_subcommand_not_allowed" in result.output

    def test_validate_git_command_non_git_command(self, tmp_path):
        """Test _validate_git_command with non-git command."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        result = backend._validate_git_command("ls -la")
        assert result is not None
        assert result.exit_code == 1
        assert "[ERROR]" in result.output
        assert "not_git_command" in result.output

    def test_validate_git_command_empty_command(self, tmp_path):
        """Test _validate_git_command with empty command."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        result = backend._validate_git_command("")
        assert result is not None
        assert result.exit_code == 1

    def test_validate_git_command_dangerous_pattern(self, tmp_path):
        """Test _validate_git_command with dangerous pattern."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        result = backend._validate_git_command("git commit --force -m 'test'")
        assert result is not None
        assert "[ERROR]" in result.output
        assert "dangerous_pattern_detected" in result.output

    def test_validate_git_command_with_pipe(self, tmp_path):
        """Test _validate_git_command with pipe (dangerous)."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        result = backend._validate_git_command("git status | cat")
        assert result is not None
        assert "[ERROR]" in result.output
        assert "dangerous_pattern_detected" in result.output

    def test_execute_git_status_success(self, tmp_path, monkeypatch):
        """Test execute() with successful git status."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )

        # Mock subprocess.run
        mock_result = MagicMock()
        mock_result.stdout = "On branch main"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            response = backend.execute("git status")
            assert response.exit_code == 0
            assert "On branch main" in response.output
            mock_run.assert_called_once()

    def test_execute_invalid_command(self, tmp_path, monkeypatch):
        """Test execute() with invalid git command."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )
        response = backend.execute("git unknown-cmd")
        assert response.exit_code == 1
        assert "[ERROR]" in response.output

    def test_execute_command_with_timeout(self, tmp_path, monkeypatch):
        """Test execute() with timeout."""
        backend = AgentHubBackend(
            agenthub_dir=tmp_path / ".agenthub",
            agent_id="test-agent",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("cmd", 30)
            response = backend.execute("git status", timeout=30)
            assert response.exit_code == 124
            assert "[ERROR]" in response.output
            assert "command_timeout" in response.output


class TestCreateAgentBackend:
    """Tests for create_agent_backend factory function."""

    def test_create_agent_backend(self, tmp_path):
        """Test create_agent_backend creates correct backend."""
        agent_dir = tmp_path / ".agenthub" / "test-agent"
        backend = create_agent_backend(
            agent_id="test-agent",
            agenthub_dir=tmp_path / ".agenthub",
        )
        assert backend.agent_id == "test-agent"
        assert backend.agenthub_dir == tmp_path / ".agenthub"
        assert agent_dir.exists()

    def test_create_agent_backend_creates_directory(self, tmp_path):
        """Test that create_agent_backend creates the agent directory."""
        agent_dir = tmp_path / ".agenthub" / "new-agent"
        assert not agent_dir.exists()

        backend = create_agent_backend(
            agent_id="new-agent",
            agenthub_dir=tmp_path / ".agenthub",
        )
        assert backend.agent_id == "new-agent"
        assert agent_dir.exists()
