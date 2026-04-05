"""Unit tests for the executor module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agenthub.core.errors import LLMError, ParseError, TimeoutError as AgentHubTimeoutError
from agenthub.runtime.executor import (
    _extract_json,
    get_executor,
    parse_evolution_result,
    parse_self_evolution_result,
    set_executor,
)


class TestParseEvolutionResult:
    """Tests for parse_evolution_result function."""

    def test_parse_valid_evolution_result(self):
        """Test parsing valid evolution result."""
        response = '''
        {
            "shouldRecord": true,
            "form": "skill",
            "scope": "universal",
            "skillName": "test-skill",
            "content": "# Test Skill content"
        }
        '''
        result = parse_evolution_result(response)
        assert result.should_record is True
        assert result.form == "skill"
        assert result.scope == "universal"
        assert result.skill_name == "test-skill"
        assert result.content == "# Test Skill content"

    def test_parse_evolution_result_no_record(self):
        """Test parsing evolution result with shouldRecord=false."""
        response = '{"shouldRecord": false, "form": "none"}'
        result = parse_evolution_result(response)
        assert result.should_record is False
        assert result.form == "none"

    def test_parse_evolution_result_with_underscores(self):
        """Test parsing evolution result with underscore field names."""
        response = '''
        {
            "should_record": true,
            "form": "experience",
            "scope": "project_specific",
            "skill_name": "my-experience",
            "content": "Experience content"
        }
        '''
        result = parse_evolution_result(response)
        assert result.should_record is True
        assert result.form == "experience"
        assert result.skill_name == "my-experience"

    def test_parse_evolution_result_in_json_code_block(self):
        """Test parsing evolution result wrapped in code block."""
        response = '''
        Here is the result:
        ```json
        {
            "shouldRecord": true,
            "form": "skill",
            "scope": "universal",
            "skillName": "code-review",
            "content": "# Code Review Skill"
        }
        ```
        '''
        result = parse_evolution_result(response)
        assert result.should_record is True
        assert result.skill_name == "code-review"

    def test_parse_evolution_result_invalid_json(self):
        """Test parsing invalid JSON raises ParseError."""
        response = "This is not JSON"
        with pytest.raises(ParseError) as exc_info:
            parse_evolution_result(response)
        assert "Failed to parse evolution result" in str(exc_info.value)


class TestParseSelfEvolutionResult:
    """Tests for parse_self_evolution_result function."""

    def test_parse_valid_self_evolution_result(self):
        """Test parsing valid self-evolution result."""
        response = '''
        {
            "hasChanges": true,
            "changes": [
                {
                    "type": "add_skill",
                    "path": "skills/new-skill/SKILL.md",
                    "content": "# New Skill"
                }
            ]
        }
        '''
        result = parse_self_evolution_result(response)
        assert result.has_changes is True
        assert len(result.changes) == 1
        assert result.changes[0].type == "add_skill"
        assert result.changes[0].path == "skills/new-skill/SKILL.md"

    def test_parse_self_evolution_no_changes(self):
        """Test parsing self-evolution result with no changes."""
        response = '{"hasChanges": false, "changes": []}'
        result = parse_self_evolution_result(response)
        assert result.has_changes is False
        assert result.changes == []

    def test_parse_self_evolution_multiple_changes(self):
        """Test parsing self-evolution result with multiple changes."""
        response = '''
        {
            "hasChanges": true,
            "changes": [
                {
                    "type": "add_skill",
                    "path": "skills/skill1/SKILL.md",
                    "content": "# Skill 1"
                },
                {
                    "type": "update_skill",
                    "path": "skills/skill2/SKILL.md",
                    "content": "# Updated Skill 2"
                },
                {
                    "type": "add_experience",
                    "path": "memory/experience1.md",
                    "content": "Experience content"
                }
            ]
        }
        '''
        result = parse_self_evolution_result(response)
        assert result.has_changes is True
        assert len(result.changes) == 3
        assert result.changes[0].type == "add_skill"
        assert result.changes[1].type == "update_skill"
        assert result.changes[2].type == "add_experience"

    def test_parse_self_evolution_in_code_block(self):
        """Test parsing self-evolution result in code block."""
        response = '''
        ```json
        {
            "hasChanges": true,
            "changes": [
                {
                    "type": "add_skill",
                    "path": "skills/test/SKILL.md",
                    "content": "# Test"
                }
            ]
        }
        ```
        '''
        result = parse_self_evolution_result(response)
        assert result.has_changes is True
        assert len(result.changes) == 1

    def test_parse_self_evolution_invalid_json(self):
        """Test parsing invalid JSON raises ParseError."""
        response = "Not valid JSON"
        with pytest.raises(ParseError) as exc_info:
            parse_self_evolution_result(response)
        assert "Failed to parse self-evolution result" in str(exc_info.value)


class TestExtractJson:
    """Tests for _extract_json helper function."""

    def test_extract_json_from_code_block(self):
        """Test extracting JSON from code block."""
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_without_code_block(self):
        """Test extracting JSON without code block."""
        text = '{"key": "value"}'
        result = _extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_json_with_extra_text(self):
        """Test extracting JSON from text with extra content."""
        text = 'Some text before {"key": "value"} and some text after'
        result = _extract_json(text)
        assert '{"key": "value"}' in result


class TestExecutorSingleton:
    """Tests for executor singleton management."""

    def test_get_executor_returns_instance(self):
        """Test get_executor returns an executor instance."""
        executor = get_executor()
        assert executor is not None

    def test_set_executor(self):
        """Test set_executor changes the global instance."""
        mock_executor = MagicMock()
        set_executor(mock_executor)
        assert get_executor() is mock_executor

    def test_get_executor_after_set(self):
        """Test get_executor returns the set instance."""
        mock_executor = MagicMock()
        set_executor(mock_executor)
        result = get_executor()
        assert result is mock_executor
