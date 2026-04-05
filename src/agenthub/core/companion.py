"""Companion module for Pokemon Avatar feature."""

from __future__ import annotations

from agenthub.core.config import get_config
from agenthub.core.pokemon_db import (
    deterministic_random_pick,
    get_random_pokemon,
    hash_string,
    lookup_pokemon_by_name,
)
from agenthub.core.types import PokemonData


def get_pokemon_avatar(
    agent_id: str,
    requested_name: str | None = None,
) -> tuple[PokemonData, str]:
    """Get Pokemon avatar for an agent.

    Logic:
    1. If user provided name and it matches a Pokemon -> use matched Pokemon name
    2. If user provided name but no match -> random Pokemon + user name
    3. If no name -> deterministic random based on stable name_hash

    Note:
        Pokemon selection uses name_hash (stable) instead of agent_id to ensure
        deterministic behavior. Same name always produces same Pokemon.

    Args:
        agent_id: Unique agent identifier (used for fallback and logging)
        requested_name: User-provided name for deterministic selection

    Returns:
        Tuple of (PokemonData, agent_name)
    """
    config = get_config()
    salt = config.pokemon_salt

    # Case 1: User provided name and it matches a Pokemon
    if requested_name:
        matched = lookup_pokemon_by_name(requested_name)
        if matched:
            # User name matches a Pokemon -> use Pokemon name
            pokemon_data = PokemonData(**matched)
            return pokemon_data, pokemon_data.name

    # Case 2: User provided name but no match -> random Pokemon + user name
    if requested_name:
        random_pokemon = get_random_pokemon()
        pokemon_data = PokemonData(**random_pokemon)
        return pokemon_data, requested_name

    # Case 3: No user name -> deterministic random based on stable hash
    # 使用稳定的 hash（requested_name or agent_id）而不是带 timestamp 的 agent_id
    # 这样同 name 永远得到同 Pokemon
    name_for_hash = requested_name or agent_id
    name_hash = hash_string(name_for_hash + salt)
    pokemon_dict, pokemon_name = deterministic_random_pick(str(name_hash), salt)
    pokemon_data = PokemonData(**pokemon_dict)
    return pokemon_data, pokemon_name


def get_personality(user_personality: str | None) -> str | None:
    """Pass through user-provided personality.

    This function is a passthrough - personality generation happens
    in the Skill Layer based on Pokemon type/abilities.

    Args:
        user_personality: User-provided personality string (optional)

    Returns:
        The same personality string if provided, None otherwise
    """
    return user_personality
