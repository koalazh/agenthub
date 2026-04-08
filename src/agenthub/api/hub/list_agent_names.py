"""List available agent names API."""

from __future__ import annotations

from agenthub.core.pokemon_db import get_all_pokemon_names


async def list_agent_names() -> list[str]:
    """Return all available agent names (Pokemon names).

    Returns:
        List of all available agent names.
    """
    return get_all_pokemon_names()
