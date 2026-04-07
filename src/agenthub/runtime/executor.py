"""Skill Executor - Core runtime for executing skills using deepagents."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from deepagents import create_deep_agent
from deepagents.backends.composite import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from agenthub.backend.agenthub_backend import AgentHubBackend
from agenthub.core.config import get_config, get_default_model, resolve_model
from agenthub.core.errors import LLMError, ParseError
from agenthub.core.errors import TimeoutError as AgentHubTimeoutError
from agenthub.core.types import (
    Change,
    EvolutionResult,
    SelfEvolutionResult,
    SkillEvent,
)

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Executes skills using deepagents.

    Each execution creates a new deep agent with the appropriate skills and context.
    Uses progressive disclosure - skill metadata is injected into the system prompt
    and the LLM decides when to use which skill based on the task description.
    """

    model: BaseChatModel

    def __init__(
        self,
        model: str | BaseChatModel = "anthropic:claude-sonnet-4-6",
        agenthub_dir: str | None = None,
    ) -> None:
        """Initialize the SkillExecutor.

        Args:
            model: Model to use for skill execution (string or BaseChatModel instance)
            agenthub_dir: Optional custom agenthub directory
        """
        if isinstance(model, str):
            self.model = resolve_model(model)
        else:
            self.model = model

        self.config = get_config()
        if agenthub_dir:
            self.config.agenthub_dir = Path(agenthub_dir)
        self.config.ensure_dirs()

    def _get_skill_paths(self, agent_id: str | None = None, scope: str = "agent") -> list[str]:
        """Get list of skill source paths (POSIX relative paths).

        Skills are loaded via CompositeBackend routing, so paths use POSIX
        conventions and are relative to the backend root.

        Args:
            agent_id: Optional agent ID to include agent-specific skills
            scope: "agenthub" for hub-level skills, "agent" for per-agent skills

        Returns:
            List of POSIX skill directory paths (relative to backend root)
        """
        if scope == "agenthub":
            # AgentHub 视角: 加载 hub-level skills from package
            # Routes: /builtin_skills/ -> package builtin_skills_dir
            return ["/builtin_skills/hub"]
        else:
            # Agent 视角: 加载 builtin skills from package + agent's own skills
            # Routes: /builtin_skills/ -> package builtin_skills_dir
            #         /skills/ -> agent's skills directory
            paths = ["/builtin_skills/agent"]
            if agent_id:
                paths.append("/skills/builtin")
            return paths

    def _build_user_message(self, task_description: str, context: dict[str, Any]) -> str:
        """Build user message for skill execution.

        Uses progressive disclosure - the task description and context guide
        the LLM to select appropriate skills without explicitly naming them.

        Args:
            task_description: Description of the task to perform
            context: Additional context for the task

        Returns:
            Formatted user message
        """
        parts = [
            "## TASK",
            "",
            task_description,
            "",
            "## Context",
            "",
        ]

        for key, value in context.items():
            parts.append(f"- {key}: {value}")

        parts.extend([
            "",
            "## Instructions",
            "",
            "1. Analyze the task and available skills",
            "2. Use appropriate tools to complete the task",
            "3. Return results in the specified JSON format",
        ])

        return "\n".join(parts)

    def _create_agent(self, agent_id: str, scope: str = "agent") -> Any:  # noqa: ANN401
        """Create a deep agent with backend and skills.

        Uses CompositeBackend to route:
        - /builtin_skills/* -> package's builtin_skills directory (read-only templates)
        - /skills/* -> agent's own skills directory (writable)
        - other paths -> AgentHubBackend for agent files

        Args:
            agent_id: Agent ID to execute within
            scope: "agenthub" (sees all agents) or "agent" (sees only own directory)

        Returns:
            Configured deep agent instance
        """
        if scope == "agenthub":
            # AgentHub 视角: 可以访问所有 agent 目录
            # Default backend: 无限制访问 agenthub_dir
            # Use virtual_mode=True so virtual paths (e.g. /soul.md) are resolved
            # relative to root_dir, not as absolute filesystem paths
            default_backend = AgentHubBackend(
                agenthub_dir=self.config.agenthub_dir,
                agent_id="",
                virtual_mode=True,  # 虚拟路径模式
                root_dir=self.config.agenthub_dir,
            )
            # Builtin skills from package directory
            # Use virtual_mode=True for proper path handling across platforms
            builtin_routes = {
                "/builtin_skills/": FilesystemBackend(
                    root_dir=str(self.config.builtin_skills_dir),
                    virtual_mode=True,
                ),
            }
        else:
            # Agent 视角: 只能看到自己
            # Default backend: 限制访问 agent 目录
            default_backend = AgentHubBackend(
                agenthub_dir=self.config.agenthub_dir,
                agent_id=agent_id,
                virtual_mode=True,  # 启用路径限制
                root_dir=self.config.agenthub_dir / agent_id,
            )
            # Builtin skills from package + agent's own skills
            # Use virtual_mode=True for proper path handling across platforms
            builtin_routes = {
                "/builtin_skills/": FilesystemBackend(
                    root_dir=str(self.config.builtin_skills_dir),
                    virtual_mode=True,
                ),
                "/skills/": FilesystemBackend(
                    root_dir=str(self.config.agenthub_dir / agent_id / "skills"),
                    virtual_mode=True,
                ),
            }

        # Create composite backend with routing
        backend = CompositeBackend(
            default=default_backend,
            routes=builtin_routes,  # type: ignore[arg-type]
        )

        return create_deep_agent(
            model=self.model,
            skills=self._get_skill_paths(agent_id, scope),
            backend=backend,
        )

    async def _invoke_agent(
        self,
        agent: Any,  # noqa: ANN401
        messages: list[HumanMessage],
        timeout: int | None = None,  # noqa: ASYNC109
    ) -> Any:  # noqa: ANN401
        """Invoke agent with optional timeout.

        Args:
            agent: The agent to invoke
            messages: Messages to send
            timeout: Optional timeout in seconds

        Returns:
            Agent response
        """
        if timeout:
            async with asyncio.timeout(timeout):
                return await agent.ainvoke(  # type: ignore[call-overload]
                    {"messages": messages},
                    config={"recursion_limit": 100},
                )
        return await agent.ainvoke(  # type: ignore[call-overload]
            {"messages": messages},
            config={"recursion_limit": 100},
        )

    async def execute(
        self,
        skill_name: str,
        task_description: str,
        agent_id: str,
        context: dict[str, Any],
        timeout: int | None = None,  # noqa: ASYNC109
        scope: str = "agent",
    ) -> str:
        """Execute a skill synchronously.

        Args:
            skill_name: Name of the skill (for logging only)
            task_description: Description of the task
            agent_id: Agent ID to execute within
            context: Additional context
            timeout: Optional timeout in seconds
            scope: "agenthub" or "agent" (default: "agent")

        Returns:
            Execution result as string
        """
        logger.info(f"Executing skill '{skill_name}' for agent '{agent_id}' (scope={scope})")

        user_message = self._build_user_message(task_description, context)
        agent = self._create_agent(agent_id, scope)

        try:
            # Execute agent with optional timeout
            messages = [HumanMessage(content=user_message)]
            result = await self._invoke_agent(agent, messages, timeout)

            # Extract response
            return self._extract_response(result)

        except asyncio.TimeoutError:
            logger.error(f"Skill execution timed out after {timeout} seconds")
            raise AgentHubTimeoutError(f"Skill execution timed out after {timeout} seconds") from None
        except Exception as e:
            logger.error(f"Skill execution failed: {e}")
            raise LLMError(f"Skill execution failed: {e}") from e

    async def execute_stream(
        self,
        skill_name: str,
        task_description: str,
        agent_id: str,
        context: dict[str, Any],
        timeout: int | None = None,  # noqa: ASYNC109
        scope: str = "agent",
    ) -> AsyncIterator[SkillEvent]:
        """Execute a skill with streaming events.

        Args:
            skill_name: Name of the skill (for logging only)
            task_description: Description of the task
            agent_id: Agent ID to execute within
            context: Additional context
            timeout: Optional timeout in seconds
            scope: "agenthub" or "agent" (default: "agent")

        Yields:
            SkillEvent objects for each chunk, tool call, etc.
        """
        logger.info(f"Executing skill '{skill_name}' with streaming for agent '{agent_id}' (scope={scope})")

        user_message = self._build_user_message(task_description, context)
        agent = self._create_agent(agent_id, scope)

        try:
            if timeout:
                async with asyncio.timeout(timeout):
                    async for chunk in agent.astream(  # type: ignore[call-overload]
                        {"messages": [HumanMessage(content=user_message)]},
                        config={"recursion_limit": 100},
                    ):
                        for event in self._process_stream_chunk(chunk):
                            yield event
            else:
                async for chunk in agent.astream(  # type: ignore[call-overload]
                    {"messages": [HumanMessage(content=user_message)]},
                    config={"recursion_limit": 100},
                ):
                    for event in self._process_stream_chunk(chunk):
                        yield event

            yield SkillEvent(type="done", content="Execution completed")

        except asyncio.TimeoutError:
            logger.error(f"Streaming skill execution timed out after {timeout} seconds")
            yield SkillEvent(type="error", content=f"Timeout after {timeout} seconds")
        except Exception as e:
            logger.error(f"Streaming skill execution failed: {e}")
            yield SkillEvent(type="error", content=f"Error: {str(e)}")

    def _process_stream_chunk(self, chunk: Any) -> Iterator[SkillEvent]:  # noqa: ANN401
        """Process a stream chunk and yield skill events.

        Args:
            chunk: Stream chunk from agent

        Yields:
            SkillEvent objects
        """
        if isinstance(chunk, dict):
            if "messages" in chunk:
                for msg in chunk["messages"]:
                    content = self._message_to_content(msg)
                    if content:
                        yield SkillEvent(type="chunk", content=content)
            elif "tool_call" in chunk:
                yield SkillEvent(
                    type="tool_call",
                    content=str(chunk.get("tool_call", "")),
                    tool_name=chunk.get("tool_name"),
                    tool_input=chunk.get("tool_input"),
                )
            elif "tool_result" in chunk:
                yield SkillEvent(
                    type="tool_result",
                    content=str(chunk.get("tool_result", "")),
                    tool_name=chunk.get("tool_name"),
                )

    def _message_to_content(self, msg: Any) -> str | None:  # noqa: ANN401
        """Extract content from a message object.

        Args:
            msg: Message object

        Returns:
            String content or None
        """
        if hasattr(msg, "content"):
            if isinstance(msg.content, str):
                return msg.content
            elif isinstance(msg.content, list):
                return "".join(
                    block.get("text", "")
                    for block in msg.content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
        return None

    def _extract_response(self, result: Any) -> str:  # noqa: ANN401
        """Extract the response text from agent result.

        Args:
            result: Agent execution result

        Returns:
            Response as string
        """
        if isinstance(result, dict):
            if "messages" in result:
                messages = result["messages"]
                if messages:
                    last_msg = messages[-1]
                    content = self._message_to_content(last_msg)
                    if content:
                        return content
            return str(result)
        return str(result)


# Global executor instance
_executor: SkillExecutor | None = None

# Pre-compiled regex patterns for JSON extraction
_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def get_executor() -> SkillExecutor:
    """Get the global SkillExecutor instance."""
    global _executor
    if _executor is None:
        _executor = SkillExecutor(model=get_default_model())
    return _executor


def set_executor(executor: SkillExecutor) -> None:
    """Set the global SkillExecutor instance."""
    global _executor
    _executor = executor


def parse_evolution_result(response: str) -> EvolutionResult:
    """Parse evolution result from LLM response.

    Args:
        response: LLM response string

    Returns:
        EvolutionResult object

    Raises:
        ParseError: If response cannot be parsed
    """
    try:
        # Try to extract JSON from the response
        json_str = _extract_json(response)
        data = json.loads(json_str)

        return EvolutionResult(
            should_record=data.get("shouldRecord", data.get("should_record", False)),
            form=data.get("form", "none"),
            confidence=data.get("confidence", "medium"),
            skill_name=data.get("skillName", data.get("skill_name")),
            scope=data.get("scope"),
            experience_type=data.get("experienceType", data.get("experience_type")),
            projects=data.get("projects", []),
            skip_reason=data.get("skipReason", data.get("skip_reason")),
            content=data.get("content"),
            commit_hash=data.get("commitHash", data.get("commit_hash")),
        )
    except json.JSONDecodeError as e:
        raise ParseError(f"Failed to parse evolution result: {e}") from e


def parse_self_evolution_result(response: str) -> SelfEvolutionResult:
    """Parse self-evolution result from LLM response.

    Args:
        response: LLM response string

    Returns:
        SelfEvolutionResult object

    Raises:
        ParseError: If response cannot be parsed
    """
    try:
        json_str = _extract_json(response)
        data = json.loads(json_str)

        changes: list[Change] = []
        for change_data in data.get("changes", []):
            changes.append(
                Change(
                    type=change_data.get("type", "add_skill"),
                    action=change_data.get("action"),
                    path=change_data.get("path", ""),
                    skill_name=change_data.get("skillName", change_data.get("skill_name")),
                    scope=change_data.get("scope"),
                    experience_type=change_data.get("experienceType", change_data.get("experience_type")),
                    projects=change_data.get("projects", []),
                    content=change_data.get("content", ""),
                    reason=change_data.get("reason"),
                )
            )

        return SelfEvolutionResult(
            has_changes=data.get("hasChanges", data.get("has_changes", False)),
            changes=changes,
        )

    except json.JSONDecodeError as e:
        raise ParseError(f"Failed to parse self-evolution result: {e}") from e


def _extract_json(text: str) -> str:
    """Extract JSON string from text that may contain extra content.

    Args:
        text: Text that may contain JSON

    Returns:
        Extracted JSON string
    """
    # Match JSON in code blocks
    code_block_match = _CODE_BLOCK_RE.search(text)
    if code_block_match:
        return code_block_match.group(1)

    # Try to find any JSON object
    json_match = _JSON_OBJECT_RE.search(text)
    if json_match:
        return json_match.group(0)

    # Return original text and let json.loads handle it
    return text.strip()
