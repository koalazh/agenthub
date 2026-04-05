"""Unit tests for FastAPI HTTP routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agenthub.api.routes import app
from agenthub.core.errors import AgentHubError, NotFoundError


class TestHTTPRoutes:
    """Tests for HTTP routes."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_root(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "AgentHub API"
        assert data["version"] == "0.1.0"

    @patch("agenthub.api.routes.run_list_agents")
    def test_list_agents(self, mock_list, client):
        """Test list agents endpoint."""
        mock_agent = MagicMock()
        mock_agent.id = "test-123"
        mock_agent.name = "test-agent"
        mock_agent.created_at.isoformat.return_value = "2026-03-30T00:00:00"
        mock_list.return_value = [mock_agent]

        response = client.get("/agents")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["agent_id"] == "test-123"

    @patch("agenthub.api.routes.run_get_agent")
    def test_get_agent_not_found(self, mock_get, client):
        """Test get agent with non-existent ID."""
        mock_get.side_effect = NotFoundError("Agent not found")

        response = client.get("/agents/nonexistent")
        assert response.status_code == 404

    @patch("agenthub.api.routes.run_export")
    def test_export_config(self, mock_export, client):
        """Test export claude-code endpoint."""
        mock_config = MagicMock()
        mock_config.model_dump.return_value = {
            "agent_id": "test-123",
            "agent_name": "test",
            "version": "v1.0",
            "system_prompt": "You are helpful",
            "model": None,
            "permission_mode": "auto",
            "allowed_tools": ["Read", "Edit"],
            "skills_dir": "/path/to/skills",
            "memory_dir": "/path/to/memory",
            "subagents": [],
        }
        mock_export.return_value = mock_config

        response = client.get("/export/claude-code?agent_id=test-123")
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-123"

    @patch("agenthub.api.routes.run_export")
    def test_export_config_not_found(self, mock_export, client):
        """Test export with non-existent agent."""
        mock_export.side_effect = NotFoundError("Agent not found")

        response = client.get("/export/claude-code?agent_id=nonexistent")
        assert response.status_code == 404

    @patch("agenthub.api.routes.run_get_history")
    def test_get_history(self, mock_get_history, client):
        """Test get evolution history endpoint."""
        mock_record = MagicMock()
        mock_record.evolution_id = "abc123"
        mock_record.timestamp.isoformat.return_value = "2026-03-30T00:00:00"
        mock_record.form = "skill"
        mock_record.skill_name = "test-skill"
        mock_record.commit_hash = "abc123def456"
        mock_record.message = "Evolution-v1: +skill test-skill"

        mock_response = MagicMock()
        mock_response.records = [mock_record]
        mock_response.total = 1
        mock_response.has_more = False
        mock_get_history.return_value = mock_response

        response = client.get("/evolution/history?agent_id=test-123")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["records"]) == 1

    @patch("agenthub.api.routes.run_rollback")
    def test_rollback(self, mock_rollback, client):
        """Test rollback endpoint."""
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "success": True,
            "previous_commit": "abc123",
            "new_commit": "def456",
            "warning": None,
        }
        mock_rollback.return_value = mock_response

        response = client.post("/evolution/rollback?agent_id=test-123&target=HEAD~1")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @patch("agenthub.api.routes.run_rollback")
    def test_rollback_already_at_target(self, mock_rollback, client):
        """Test rollback when already at target."""
        mock_rollback.side_effect = AgentHubError("Already at target")

        response = client.post("/evolution/rollback?agent_id=test-123&target=HEAD~1")
        assert response.status_code == 400

    def test_rollback_validation_error(self, client):
        """Test rollback with invalid target."""
        response = client.post("/evolution/rollback?agent_id=test-123&target=invalid!!")
        assert response.status_code == 422  # Validation error

    @patch("agenthub.api.routes.run_init_agent")
    def test_create_agent(self, mock_init, client):
        """Test create agent endpoint."""
        mock_agent = MagicMock()
        mock_agent.id = "test-123"
        mock_agent.name = "test-agent"
        mock_agent.created_at.isoformat.return_value = "2026-03-30T00:00:00"
        mock_init.return_value = mock_agent

        response = client.post("/agents", json={"name": "test-agent", "identity": "A helpful agent"})
        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "test-123"

    @patch("agenthub.api.routes.run_delete_agent")
    def test_delete_agent(self, mock_delete, client):
        """Test delete agent endpoint."""
        mock_delete.return_value = None

        response = client.delete("/agents/test-123")
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
