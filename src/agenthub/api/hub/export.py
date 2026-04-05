"""Export API - Generate Claude Code CLI launch configuration.

This module provides the ability to export an Agent's configuration
in a format suitable for launching via Claude Code CLI.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from agenthub.core.companion import get_pokemon_avatar
from agenthub.core.config import get_config
from agenthub.core.errors import AgentHubError, NotFoundError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemPromptSection:
    """System prompt section with ordering.

    Attributes:
        header: Markdown header (e.g. "## Agent Identity") or None for inline sections
        content: Section content
        order: Display order (lower = earlier)
    """

    header: str | None
    content: str
    order: int


# Section order constants
_SECTION_ORDER_IDENTITY = 1
_SECTION_ORDER_SOUL = 2
_SECTION_ORDER_CAPABILITIES = 3
_SECTION_ORDER_MEMORY = 4
_SECTION_ORDER_INSTRUCTIONS = 5


class SubagentConfig(BaseModel):
    """Subagent configuration for Claude Code CLI."""

    name: str = Field(..., description="Subagent name")
    description: str = Field(..., description="Subagent description")
    instructions: str = Field(..., description="Subagent instructions")


class ClaudeCodeLaunchConfig(BaseModel):
    """Claude Code CLI launch configuration.

    This is the core contract between AgentHub and agentcenter
    for launching Claude Code with an Agent's configuration.
    """

    agent_id: str = Field(..., description="Agent unique identifier")
    agent_name: str = Field(..., description="Agent name")
    version: str = Field(..., description="Agent version")
    system_prompt: str = Field(..., description="Complete rendered system prompt")
    model: str | None = Field(default=None, description="Model to use")
    permission_mode: str | None = Field(default=None, description="Permission mode")
    allowed_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Edit", "Bash", "Glob", "Grep"],
        description="Allowed tools for Claude Code",
    )
    skills_dir: str | None = Field(default=None, description="Agent skills directory path")
    memory_dir: str | None = Field(default=None, description="Agent memory directory path")
    subagents: list[SubagentConfig] = Field(default_factory=list, description="Subagent configurations")
    avatar: str | None = Field(default=None, description="Companion avatar (ASCII art)")


async def export_agent_config(
    agent_id: str,
    project_id: str | None = None,
) -> ClaudeCodeLaunchConfig:
    """Export an Agent's configuration for Claude Code CLI.

    Args:
        agent_id: ID of the agent to export
        project_id: Optional project ID to filter project-specific skills/memory

    Returns:
        ClaudeCodeLaunchConfig for starting Claude Code with this agent

    Raises:
        NotFoundError: If agent does not exist
        AgentHubError: If export fails
    """
    logger.info(f"Exporting agent config for '{agent_id}' (project_id={project_id})")

    config = get_config()
    agent_dir = config.agenthub_dir / agent_id

    if not agent_dir.exists():
        raise NotFoundError(f"Agent '{agent_id}' not found")

    # Read base files
    identity_content = _read_file_safe(agent_dir / "identity.md")
    soul_content = _read_file_safe(agent_dir / "soul.md")
    bootstrap_content = _read_file_safe(agent_dir / "BOOTSTRAP.md")

    # P0: soul.md missing warning
    if not soul_content:
        logger.warning(
            f"Agent '{agent_id}' is missing soul.md - "
            "agent will start without identity. "
            "This may cause undefined behavior."
        )

    # Scan skills directory
    skills_index = _build_skills_index(agent_dir, project_id)

    # Build memory content
    memory_content = _build_memory_content(agent_dir, project_id)

    # Build sections
    sections = _build_sections(
        identity=identity_content,
        soul=soul_content,
        bootstrap=bootstrap_content,
        skills_index=skills_index,
        memory_content=memory_content,
    )

    # Assemble system prompt
    system_prompt = _assemble_system_prompt(sections)

    # Get avatar
    avatar = _get_avatar(agent_id)

    # Get skills_dir and memory_dir paths
    skills_dir = str(agent_dir / "skills")
    memory_dir = str(agent_dir / "memory")

    return ClaudeCodeLaunchConfig(
        agent_id=agent_id,
        agent_name=agent_id.split("-")[0] if "-" in agent_id else agent_id,
        version="v1.0",
        system_prompt=system_prompt,
        model=None,
        permission_mode="auto",
        allowed_tools=["Read", "Edit", "Bash", "Glob", "Grep"],
        skills_dir=skills_dir,
        memory_dir=memory_dir,
        subagents=[],
        avatar=avatar,
    )


def _get_avatar(agent_id: str) -> str | None:
    """Get avatar for an agent.

    Priority:
    1. Read from .agenthub_meta (stable, written at init time)
    2. Fallback: generate from stable hash (for legacy agents without avatar)

    Args:
        agent_id: Agent ID

    Returns:
        Avatar string or None if unavailable
    """
    config = get_config()
    agent_dir = config.agenthub_dir / agent_id
    meta_path = agent_dir / ".agenthub_meta"
    metadata = None

    # Priority 1: Read from .agenthub_meta
    try:
        if meta_path.exists():
            metadata = json.loads(meta_path.read_text())
            if "avatar" in metadata:
                return metadata.get("avatar")
    except Exception as e:
        logger.warning(f"Failed to read avatar from .agenthub_meta: {e}")

    # Priority 2: Fallback to get_pokemon_avatar for legacy support
    try:
        name = metadata.get("name", agent_id) if metadata else agent_id
        pokemon_data, _ = get_pokemon_avatar(agent_id, name)
        return pokemon_data.ascii
    except Exception as e:
        logger.warning(f"Failed to generate avatar: {e}")
        return None


def _build_sections(
    identity: str,
    soul: str,
    bootstrap: str,
    skills_index: str,
    memory_content: str,
) -> list[SystemPromptSection]:
    """Build all system prompt sections.

    Args:
        identity: Identity content
        soul: Soul content
        bootstrap: Bootstrap content
        skills_index: Skills index content
        memory_content: Memory content

    Returns:
        List of SystemPromptSection sorted by order
    """
    sections = []

    if identity:
        sections.append(
            SystemPromptSection(
                header="## Agent Identity",
                content=identity,
                order=_SECTION_ORDER_IDENTITY,
            )
        )

    if soul:
        sections.append(
            SystemPromptSection(
                header="## Agent Soul",
                content=soul,
                order=_SECTION_ORDER_SOUL,
            )
        )

    if skills_index:
        sections.append(
            SystemPromptSection(
                header=None,  # Inline section, no header
                content=skills_index,
                order=_SECTION_ORDER_CAPABILITIES,
            )
        )

    if memory_content:
        sections.append(
            SystemPromptSection(
                header=None,  # Inline section, no header
                content=memory_content,
                order=_SECTION_ORDER_MEMORY,
            )
        )

    if bootstrap:
        sections.append(
            SystemPromptSection(
                header="## Instructions",
                content=bootstrap,
                order=_SECTION_ORDER_INSTRUCTIONS,
            )
        )

    return sections


def _assemble_system_prompt(sections: list[SystemPromptSection]) -> str:
    """Assemble complete system prompt from sections.

    Args:
        sections: List of SystemPromptSection

    Returns:
        Complete system prompt in Markdown format
    """
    sorted_sections = sorted(sections, key=lambda s: s.order)
    parts = []

    for section in sorted_sections:
        if section.header:
            parts.extend([section.header, section.content, ""])
        else:
            parts.extend([section.content, ""])

    parts.append("---")  # Footer

    return "\n".join(parts)


def _read_file_safe(file_path: Path) -> str:
    """Read file content safely, returning empty string if not found.

    Args:
        file_path: Path to file

    Returns:
        File content or empty string
    """
    try:
        if file_path.exists():
            return file_path.read_text(encoding="utf-8").strip()
    except Exception as e:
        logger.warning(f"Failed to read {file_path}: {e}")
    return ""


def _build_skills_index(agent_dir: Path, project_id: str | None) -> str:
    """Build skills index section for system prompt.

    Args:
        agent_dir: Agent directory
        project_id: Optional project ID to filter

    Returns:
        Formatted skills index string
    """
    lines = ["## Available Skills", ""]

    skills_dir = agent_dir / "skills"

    # Built-in skills
    builtin_dir = skills_dir / "builtin"
    if builtin_dir.exists():
        lines.append("### Built-in Skills")
        for skill_path in _iterate_skills(builtin_dir):
            skill_name = skill_path.parent.name + "/" + skill_path.stem
            description = _read_file_safe(skill_path).split("\n")[0][:100]
            lines.append(f"- **{skill_name}**: {description}")
        lines.append("")

    # Universal skills
    universal_dir = skills_dir / "universal"
    if universal_dir.exists():
        lines.append("### Universal Skills")
        for skill_path in _iterate_skills(universal_dir):
            skill_name = "universal/" + skill_path.stem
            description = _read_file_safe(skill_path).split("\n")[0][:100]
            lines.append(f"- **{skill_name}**: {description}")
        lines.append("")

    # Project-specific skills
    projects_dir = skills_dir / "projects"
    if projects_dir.exists():
        lines.append("### Project Skills")
        for project_subdir in projects_dir.iterdir():
            if not project_subdir.is_dir():
                continue
            # Filter by project_id if provided
            if project_id and project_subdir.name != project_id:
                continue
            for skill_path in _iterate_skills(project_subdir):
                skill_name = f"projects/{project_subdir.name}/{skill_path.stem}"
                description = _read_file_safe(skill_path).split("\n")[0][:100]
                lines.append(f"- **{skill_name}**: {description}")
        lines.append("")

    return "\n".join(lines)


def _iterate_skills(skill_dir: Path) -> list[Path]:
    """Iterate over skill files in a directory.

    Args:
        skill_dir: Skills directory

    Returns:
        List of skill file paths (skill.md or skillname.md), deduplicated
    """
    skills: list[Path] = []
    if not skill_dir.exists():
        return skills

    seen: set[str] = set()

    for item in skill_dir.iterdir():
        if item.is_file() and item.suffix == ".md":
            if str(item) not in seen:
                skills.append(item)
                seen.add(str(item))
        elif item.is_dir():
            # For each subdirectory, only add skill.md if it exists
            skill_md = item / "skill.md"
            if skill_md.exists() and str(skill_md) not in seen:
                skills.append(skill_md)
                seen.add(str(skill_md))
    return skills


def _build_memory_content(agent_dir: Path, project_id: str | None) -> str:
    """Build memory content section for system prompt.

    Args:
        agent_dir: Agent directory
        project_id: Optional project ID to filter

    Returns:
        Formatted memory content string
    """
    memory_dir = agent_dir / "memory"
    if not memory_dir.exists():
        return ""

    lines = ["## Memory", ""]

    projects_dir = memory_dir / "projects"
    if projects_dir.exists():
        # Universal memory
        universal_dir = projects_dir / "universal"
        if universal_dir.exists():
            lines.append("### Universal Memory")
            for mem_file in universal_dir.glob("*.md"):
                content = _read_file_safe(mem_file)
                if content:
                    lines.append(f"#### From {mem_file.stem}")
                    lines.append(content[:500] + "..." if len(content) > 500 else content)
                    lines.append("")
            lines.append("")

        # Project-specific memory
        if project_id:
            project_mem_dir = projects_dir / project_id
            if project_mem_dir.exists():
                lines.append(f"### Memory for project: {project_id}")
                for mem_file in project_mem_dir.glob("*.md"):
                    content = _read_file_safe(mem_file)
                    if content:
                        lines.append(f"#### From {mem_file.stem}")
                        lines.append(content[:500] + "..." if len(content) > 500 else content)
                        lines.append("")
                lines.append("")

    return "\n".join(lines)
