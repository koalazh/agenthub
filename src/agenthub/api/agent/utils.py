"""Shared utilities for agent APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def read_if_exists(path: Path) -> str:
    """Read file content if it exists.

    Args:
        path: File path to read

    Returns:
        File content or empty string if file does not exist
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def list_existing_skills(skills_dir: Path) -> dict[str, Any]:
    """Get agent's existing skills information.

    Args:
        skills_dir: Agent's skills directory

    Returns:
        Dict with builtin, universal, and project-specific skills
    """
    result: dict[str, Any] = {"builtin": [], "universal": [], "projects": {}}

    builtin_dir = skills_dir / "builtin"
    if builtin_dir.exists():
        result["builtin"] = [d.name for d in builtin_dir.iterdir() if d.is_dir()]

    universal_dir = skills_dir / "universal"
    if universal_dir.exists():
        result["universal"] = [d.name for d in universal_dir.iterdir() if d.is_dir()]

    projects_dir = skills_dir / "projects"
    if projects_dir.exists():
        result["projects"] = {
            d.name: [s.name for s in d.iterdir() if s.is_dir()]
            for d in projects_dir.iterdir()
            if d.is_dir()
        }

    return result
