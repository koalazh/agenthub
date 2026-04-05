"""Pytest configuration and fixtures for AgentHub tests."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agenthub.api.routes import app
from agenthub.core.config import AgentHubConfig, get_config, set_config
from agenthub.runtime.executor import SkillExecutor, set_executor


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path: Path, monkeypatch):
    """Set up test environment with isolated agenthub directory.

    This fixture runs automatically for all tests to ensure they use
    an isolated temp directory as the AgentHub data directory.
    """
    test_agenthub_dir = tmp_path / ".agenthub"
    test_agenthub_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENTHUB_DIR", str(test_agenthub_dir))

    # Reset the global config so it picks up the new env var
    config = AgentHubConfig(agenthub_dir=test_agenthub_dir)
    set_config(config)


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def temp_agent_dir():
    """Create a temporary agent directory with git repo initialized.

    This fixture creates a complete agent directory structure under the
    AGENTHUB_DIR (set by setup_test_env) for E2E testing of export,
    rollback, and history operations.
    """
    agent_id = "e2e-test-agent"
    agenthub_dir = Path(os.environ["AGENTHUB_DIR"])
    agent_dir = agenthub_dir / agent_id
    agent_dir.mkdir(parents=True)

    # Create directory structure
    (agent_dir / "skills" / "builtin").mkdir(parents=True)
    (agent_dir / "skills" / "universal").mkdir(parents=True)
    (agent_dir / "skills" / "projects").mkdir(parents=True)
    (agent_dir / "memory" / "projects" / "universal").mkdir(parents=True)
    (agent_dir / "archives").mkdir()

    # Create bootstrap files
    (agent_dir / "soul.md").write_text("You are a helpful assistant.", encoding="utf-8")
    (agent_dir / "identity.md").write_text("I am an AI coding agent.", encoding="utf-8")
    (agent_dir / "BOOTSTRAP.md").write_text("Always write tests first.", encoding="utf-8")

    # Create a skill
    (agent_dir / "skills" / "builtin" / "evolution.md").write_text(
        "# Evolution Skill\nAnalyzes transcripts and records insights.",
        encoding="utf-8",
    )

    # Create memory
    (agent_dir / "memory" / "projects" / "universal" / "experience.md").write_text(
        "# Experience\nLearned to write tests first.",
        encoding="utf-8",
    )

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=agent_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "e2e@test.com"],
        cwd=agent_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "E2E Test"],
        cwd=agent_dir,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    subprocess.run(["git", "add", "."], cwd=agent_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial setup"],
        cwd=agent_dir,
        check=True,
        capture_output=True,
    )

    yield agent_dir

    # Cleanup handled by tmp_path fixture


@pytest.fixture
def mock_executor():
    """Mock executor for tests that need LLM bootstrap generation.

    This fixture provides a mock SkillExecutor that returns canned bootstrap
    content without calling a real LLM API. Use this for tests that need
    to create agents via the API.
    """
    from agenthub.core.config import get_config

    mock = MagicMock(spec=SkillExecutor)

    # Mock execute to return canned bootstrap content (new format with files_written)
    async def mock_execute(*args, **kwargs):
        # Get agent_id from kwargs (passed by init_agent)
        agent_id = kwargs.get("agent_id")
        if agent_id:
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
    mock.execute_stream = AsyncMock(return_value=iter([]))

    # Save original executor and set mock
    original_executor = SkillExecutor._executor if hasattr(SkillExecutor, '_executor') else None
    set_executor(mock)

    yield mock

    # Restore original executor
    if original_executor is not None:
        set_executor(original_executor)


@pytest.fixture
def agent_with_history(temp_agent_dir: Path):
    """Create an agent with multiple evolution commits for history testing.

    This fixture creates a git history with evolution commits that can be used
    to test the history API.
    """
    # Create evolution commits
    commits = [
        ("Evolution-v1: +skill test-skill-1", "First skill"),
        ("Evolution-v1: +experience test-exp-1", "First experience"),
        ("Evolution-v1: +skill test-skill-2", "Second skill"),
    ]

    for commit_msg, _ in commits:
        # Create a dummy file
        dummy_file = temp_agent_dir / f"{commit_msg.split()[-1]}.md"
        dummy_file.write_text(f"Content for {commit_msg}", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=temp_agent_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=temp_agent_dir,
            check=True,
            capture_output=True,
        )

    yield temp_agent_dir
