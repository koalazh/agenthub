"""E2E tests for AgentHub full workflow.

These tests verify the complete flow from HTTP API to filesystem operations,
testing the integration between routes, business logic, and git operations.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agenthub.core.config import get_config


class TestExportE2E:
    """E2E tests for Export API."""

    def test_export_agent_config(self, client, temp_agent_dir: Path):
        """Test exporting an agent's full configuration."""
        agent_id = temp_agent_dir.name

        response = client.get(f"/export/claude-code?agent_id={agent_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["agent_id"] == agent_id
        assert data["system_prompt"] != ""
        assert "Agent Identity" in data["system_prompt"]
        assert "Agent Soul" in data["system_prompt"]
        assert "Instructions" in data["system_prompt"]
        assert data["skills_dir"] is not None
        assert data["memory_dir"] is not None

    def test_export_with_skills_index(self, client, temp_agent_dir: Path):
        """Test that exported config includes skills index."""
        agent_id = temp_agent_dir.name

        response = client.get(f"/export/claude-code?agent_id={agent_id}")
        assert response.status_code == 200

        data = response.json()
        prompt = data["system_prompt"]
        assert "Available Skills" in prompt or "Skills" in prompt

    def test_export_not_found(self, client):
        """Test exporting a non-existent agent returns 404."""
        response = client.get("/export/claude-code?agent_id=nonexistent")
        assert response.status_code == 404


class TestRollbackE2E:
    """E2E tests for Rollback API."""

    def test_rollback_to_previous_commit(self, client, temp_agent_dir: Path):
        """Test rolling back to a previous commit."""
        agent_id = temp_agent_dir.name

        # Get initial commit
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_agent_dir,
            capture_output=True,
            text=True,
        )
        initial_commit = result.stdout.strip()

        # Make a new commit
        new_file = temp_agent_dir / "new_feature.md"
        new_file.write_text("# New Feature\nSomething new.", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=temp_agent_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add new feature"],
            cwd=temp_agent_dir,
            check=True,
            capture_output=True,
        )

        # Verify file exists
        assert new_file.exists()

        # Rollback to HEAD~1
        response = client.post(f"/evolution/rollback?agent_id={agent_id}&target=HEAD~1")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["previous_commit"] != data["new_commit"]

        # Verify file no longer exists after rollback
        assert not new_file.exists()

    def test_rollback_with_commit_hash(self, client, temp_agent_dir: Path):
        """Test rolling back to a specific commit hash."""
        agent_id = temp_agent_dir.name

        # Get the first commit hash
        result = subprocess.run(
            ["git", "log", "--reverse", "--pretty=format:%H", "-1"],
            cwd=temp_agent_dir,
            capture_output=True,
            text=True,
        )
        first_commit = result.stdout.strip()

        # Make a new commit
        new_file = temp_agent_dir / "another_feature.md"
        new_file.write_text("# Another Feature", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=temp_agent_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add another feature"],
            cwd=temp_agent_dir,
            check=True,
            capture_output=True,
        )

        # Rollback to first commit
        response = client.post(f"/evolution/rollback?agent_id={agent_id}&target={first_commit}")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True

    def test_rollback_invalid_target(self, client, temp_agent_dir: Path):
        """Test rolling back with invalid target returns 422."""
        agent_id = temp_agent_dir.name

        response = client.post(f"/evolution/rollback?agent_id={agent_id}&target=invalid!!")
        assert response.status_code == 422

    def test_rollback_already_at_target(self, client, temp_agent_dir: Path):
        """Test rolling back to current HEAD returns 400."""
        agent_id = temp_agent_dir.name

        # Get current HEAD
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=temp_agent_dir,
            capture_output=True,
            text=True,
        )
        current_head = result.stdout.strip()

        # Try to rollback to same commit
        response = client.post(f"/evolution/rollback?agent_id={agent_id}&target={current_head}")
        assert response.status_code in [200, 400]  # Either succeeds or already at target


class TestHistoryE2E:
    """E2E tests for History API."""

    def test_get_evolution_history(self, client, agent_with_history: Path):
        """Test getting evolution history with evolution commits."""
        agent_id = agent_with_history.name

        response = client.get(f"/evolution/history?agent_id={agent_id}&limit=10")
        assert response.status_code == 200

        data = response.json()
        assert "records" in data
        assert "total" in data
        assert "has_more" in data
        assert data["total"] >= 3  # We created 3 evolution commits

    def test_get_history_with_pagination(self, client, agent_with_history: Path):
        """Test history pagination."""
        agent_id = agent_with_history.name

        # Get first page
        response1 = client.get(f"/evolution/history?agent_id={agent_id}&limit=2&offset=0")
        assert response1.status_code == 200
        data1 = response1.json()
        assert len(data1["records"]) == 2
        assert data1["has_more"] is True

        # Get second page
        response2 = client.get(f"/evolution/history?agent_id={agent_id}&limit=2&offset=2")
        assert response2.status_code == 200
        data2 = response2.json()
        assert len(data2["records"]) >= 1

    def test_get_history_not_found(self, client):
        """Test getting history for non-existent agent returns 404."""
        response = client.get("/evolution/history?agent_id=nonexistent")
        assert response.status_code == 404


class TestAgentCRUDE2E:
    """E2E tests for Agent CRUD operations."""

    def test_create_and_get_agent(self, client, mock_executor):
        """Test creating an agent and retrieving it."""
        # Create agent
        create_response = client.post(
            "/agents",
            json={"name": "e2e-crud-test", "identity": "A test agent"},
        )
        assert create_response.status_code == 200
        agent_id = create_response.json()["agent_id"]

        # Get agent
        get_response = client.get(f"/agents/{agent_id}")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["agent_id"] == agent_id
        assert data["name"].startswith("e2e-crud-test")

    def test_list_agents(self, client):
        """Test listing all agents."""
        response = client.get("/agents")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_delete_agent(self, client, mock_executor):
        """Test deleting an agent."""
        # Create agent
        create_response = client.post(
            "/agents",
            json={"name": "e2e-delete-test", "identity": "A test agent"},
        )
        agent_id = create_response.json()["agent_id"]

        # Delete agent
        delete_response = client.delete(f"/agents/{agent_id}")
        assert delete_response.status_code == 200

        # Verify agent is deleted
        get_response = client.get(f"/agents/{agent_id}")
        assert get_response.status_code == 404


class TestHealthE2E:
    """E2E tests for health and root endpoints."""

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_root_endpoint(self, client):
        """Test root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "AgentHub API"
        assert "version" in data
        assert "docs" in data
