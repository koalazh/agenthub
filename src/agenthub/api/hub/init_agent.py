"""Init Agent API - AgentHub perspective.

API Layer responsibilities:
- Generate agent_id (deterministic based on name + timestamp, or UUID fallback)
- Get Pokemon avatar via get_pokemon_avatar()
- Write Pokemon data to companion.json
- Create empty directory structure
- Copy builtin skills (evolution, self-evolution) to agent's skills/builtin/
- Call executor.execute()
- Parse Skill return result
- Verify files written
- Return Agent object

Skill Layer responsibilities (init-agent Skill):
- ORIENT: Read context, generate inspirationSeed, agent_name, personality (if not provided)
- GENERATE: Write bootstrap files (soul.md, identity.md, BOOTSTRAP.md)
- FINALIZE: Git init + commit, return InitAgentResult
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError as PydanticValidationError

from agenthub.core.companion import get_pokemon_avatar, get_personality
from agenthub.core.config import get_config
from agenthub.core.errors import AgentHubError, ParseError, ValidationError
from agenthub.core.types import Agent, InitAgentConfig, InitAgentResult
from agenthub.runtime.executor import get_executor

logger = logging.getLogger(__name__)


async def init_agent(config: InitAgentConfig) -> Agent:
    """Initialize a new agent with bootstrap files.

    API Layer responsibilities:
    - Generate agent_id (deterministic based on name)
    - Create empty directory structure
    - Copy builtin skills to agent's skills/builtin/
    - Call executor.execute()
    - Parse Skill return result
    - Verify files written
    - Return Agent object

    Skill Layer responsibilities (init-agent Skill):
    - ORIENT: Read context, generate inspirationSeed, agent_name, personality
    - GENERATE: Write bootstrap files (soul.md, identity.md, BOOTSTRAP.md)
    - FINALIZE: Git init + commit, return InitAgentResult

    Args:
        config: Agent initialization configuration

    Returns:
        Created Agent object

    Raises:
        ValidationError: If config validation fails
        AgentHubError: If agent creation fails
    """
    logger.info(f"Initializing agent: {config.name}")

    # 1. Config validation
    try:
        validated_config = InitAgentConfig.model_validate(config)
    except PydanticValidationError as e:
        raise ValidationError(f"Invalid config: {e}") from e

    config_obj = get_config()

    # 2. Generate agent_id (API Layer responsibility)
    # Handle None name with UUID fallback, ensure lowercase
    agent_id = _generate_agent_id(validated_config.name)
    agent_id = agent_id.lower()
    agent_dir = config_obj.agenthub_dir / agent_id

    # 3. Get Pokemon avatar (API Layer responsibility)
    pokemon_data, agent_name = get_pokemon_avatar(agent_id, validated_config.name)

    # 4. Create directory structure (API Layer responsibility)
    try:
        _create_directory_structure(agent_dir)
    except OSError as e:
        raise AgentHubError(f"DIRECTORY_CREATE_ERROR: {e}") from e

    # 5. Write .agenthub_meta (API Layer responsibility)
    # This stores agent metadata for export/get_agent
    agenthub_meta_path = agent_dir / ".agenthub_meta"
    agenthub_meta = {
        "name": agent_name,
        "avatar": pokemon_data.ascii,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        agenthub_meta_path.write_text(json.dumps(agenthub_meta, indent=2, ensure_ascii=False))
    except OSError as e:
        raise AgentHubError(f"AGENTHUB_META_WRITE_ERROR: {e}") from e

    # 6. Copy builtin skills to agent's skills/builtin/ (API Layer responsibility)
    try:
        _copy_builtin_skills(agent_dir, config_obj.builtin_skills_dir)
    except OSError as e:
        raise AgentHubError(f"BUILTIN_SKILLS_COPY_ERROR: {e}") from e

    executor = get_executor()

    try:
        # 7. Call executor to run Skill
        result = await executor.execute(
            skill_name="init_agent",
            task_description="Initialize a new agent with bootstrap files.",
            agent_id=agent_id,
            context={
                "name": agent_name,  # Use Pokemon-matched name
                "personality": get_personality(validated_config.personality),  # Pass through or None
                "identity": validated_config.identity,
                "traits": validated_config.traits,
                "agent_id": agent_id,  # API layer generated deterministic ID
                "pokemon_data": pokemon_data.model_dump(),  # Pokemon companion data
            },
            timeout=config_obj.init_agent_timeout,
            scope="agenthub",
        )

        # 8. Parse Skill return result
        init_result = parse_init_agent_result(result)

        # 9. Verify files written
        _verify_files_written(agent_dir, init_result.files_written)

        logger.info(f"Agent '{agent_id}' initialized successfully at {agent_dir}")

        # 10. Return Agent object with Pokemon data
        # Use agent_name from Skill result, fallback to id or pokemon name
        agent_name = init_result.agent_name or pokemon_data.name if pokemon_data else agent_id
        return Agent(
            id=agent_id,
            name=agent_name,
            path=agent_dir,
            created_at=datetime.now(timezone.utc),
            avatar=pokemon_data.ascii,
        )

    except (ValidationError, AgentHubError) as e:
        # Cleanup on failure for known error types
        shutil.rmtree(agent_dir, ignore_errors=True)
        raise
    except PydanticValidationError as e:
        # Cleanup on failure for Pydantic validation errors from parse_init_agent_result
        shutil.rmtree(agent_dir, ignore_errors=True)
        raise ParseError(f"SKILL_OUTPUT_VALIDATION_ERROR: {e}") from e
    except Exception as e:
        # Cleanup on failure for unexpected errors
        shutil.rmtree(agent_dir, ignore_errors=True)
        raise AgentHubError(f"SKILL_EXECUTION_ERROR: {e}") from e


def _generate_agent_id(name: str | None) -> str:
    """Generate a unique agent ID from name.

    Args:
        name: Agent name (can be None for UUID fallback)

    Returns:
        URL-safe agent ID (lowercase)
    """
    if name:
        # Convert to lowercase, replace spaces with hyphens, remove special chars
        agent_id = re.sub(r"[^a-z0-9]+", "-", name.lower())
        agent_id = agent_id.strip("-")
        if not agent_id:
            agent_id = "agent"
    else:
        # UUID fallback for None name
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
    # Add timestamp for uniqueness
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{agent_id}-{timestamp}"


def _create_directory_structure(agent_dir: Path) -> None:
    """Create agent directory structure.

    Args:
        agent_dir: Agent root directory

    Raises:
        OSError: If directory creation fails
    """
    dirs = [
        agent_dir,
        agent_dir / "skills",
        agent_dir / "skills" / "builtin",
        agent_dir / "skills" / "universal",
        agent_dir / "skills" / "projects",
        agent_dir / "memory",
        agent_dir / "memory" / "projects",
        agent_dir / "memory" / "projects" / "universal",
        agent_dir / "archives",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def _copy_builtin_skills(agent_dir: Path, builtin_skills_dir: Path) -> None:
    """Copy builtin skills to agent's skills/builtin/ directory.

    Copies evolution and self-evolution skills from the package's builtin_skills
    directory to the agent's skills/builtin directory.

    Args:
        agent_dir: Agent root directory
        builtin_skills_dir: Package's builtin skills directory

    Raises:
        OSError: If copy operation fails
    """
    source_agent_skills = builtin_skills_dir / "agent"
    target_builtin = agent_dir / "skills" / "builtin"

    if not source_agent_skills.exists():
        logger.warning(f"Source builtin skills dir does not exist: {source_agent_skills}")
        return

    for skill_dir in source_agent_skills.iterdir():
        if skill_dir.is_dir():
            target_dir = target_builtin / skill_dir.name
            if not target_dir.exists():
                shutil.copytree(skill_dir, target_dir)
                logger.info(f"Copied builtin skill: {skill_dir.name}")


def _verify_files_written(agent_dir: Path, files_written: list[str]) -> None:
    """Verify that Skill actually wrote the expected files.

    Args:
        agent_dir: Agent root directory
        files_written: List of files that Skill reported writing

    Raises:
        AgentHubError: If expected file is not found
    """
    for filename in files_written:
        # Handle paths with directory prefixes (e.g., "/agent-id/soul.md" or "skills/skill.md")
        import os
        basename = os.path.basename(filename)
        filepath = agent_dir / basename
        if not filepath.exists():
            raise AgentHubError(f"FILE_WRITE_MISSING: expected {basename} but not found")


def parse_init_agent_result(result: str) -> InitAgentResult:
    """Parse Skill return result to InitAgentResult.

    Args:
        result: executor.execute() return value (raw string)

    Returns:
        InitAgentResult object

    Raises:
        AgentHubError: If parsing fails or Skill returned an error
    """
    from agenthub.runtime.executor import _extract_json

    try:
        json_str = _extract_json(result)
        parsed = json.loads(json_str)

        # Check if Skill returned an error
        if "error" in parsed:
            error_code = parsed["error"]
            if error_code == "AGENT_EXISTS":
                raise AgentHubError(f"AGENT_EXISTS: {parsed.get('agent_id')}")
            elif error_code == "MISSING_NAME":
                raise ValidationError("Missing required field: name")
            else:
                raise AgentHubError(f"SKILL_ERROR: {error_code}")

        # Tolerate non-standard LLM output by extracting missing fields
        # LLM sometimes returns agent_id instead of agent_name, notes instead of personality
        if "agent_name" not in parsed or not parsed["agent_name"]:
            if "agent_id" in parsed:
                parsed["agent_name"] = parsed["agent_id"].split("-")[0] if "-" in parsed["agent_id"] else parsed["agent_id"]
        if "personality" not in parsed or not parsed["personality"]:
            if "notes" in parsed and parsed["notes"]:
                # Handle both list and dict formats for notes
                notes = parsed["notes"]
                if isinstance(notes, list):
                    for note in notes:
                        if isinstance(note, str) and len(note) > 10:
                            parsed["personality"] = note
                            break
                elif isinstance(notes, dict):
                    # notes is a dict like {'personality_generated': '...'}
                    for key, value in notes.items():
                        if isinstance(value, str) and len(value) > 10:
                            parsed["personality"] = value
                            break
        # Convert notes to list if it's a dict
        if "notes" in parsed and isinstance(parsed["notes"], dict):
            parsed["notes"] = [str(parsed["notes"])]

        return InitAgentResult.model_validate(parsed)

    except json.JSONDecodeError as e:
        raise AgentHubError(f"SKILL_OUTPUT_PARSE_ERROR: {e}") from e
