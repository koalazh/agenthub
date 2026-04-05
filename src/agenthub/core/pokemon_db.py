"""Pokemon database utilities for Agent Companion."""

from __future__ import annotations

from typing import Any, Callable

from pokemon.master import get_pokemon


def hash_string(s: str) -> int:
    """FNV-1a hash algorithm.

    Args:
        s: Input string to hash

    Returns:
        32-bit unsigned integer hash value
    """
    h = 2166136261
    for c in s:
        h ^= ord(c)
        h = (h * 16777619) & 0xFFFFFFFF
    return h & 0xFFFFFFFF


def mulberry32(seed: int) -> Callable[[], float]:
    """Mulberry32 PRNG - deterministic random number generator.

    Args:
        seed: Initial seed value

    Returns:
        Callable that returns random floats in [0, 1)
    """
    a = seed & 0xFFFFFFFF
    if a == 0:
        a = 0x6D2B79F5  # Guard against seed=0 producing fixed output

    def roll() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = (a ^ (a >> 15)) * (1 | a)
        t = (t + (t >> 7) * (61 | t)) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return roll


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Get field from dict-like or class object.

    Args:
        obj: Object to get field from (dict or class instance)
        key: Field name
        default: Default value if field not found

    Returns:
        Field value or default
    """
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, key, default)


def _extract_pokemon_data(raw: Any) -> tuple[Any, str]:
    """Extract Pokemon data from raw API response.

    The pokemon API returns {pid: pokemon_data} where pid is the Pokemon ID.
    This function extracts the inner pokemon_data and returns both
    the data dict and the Pokemon name.

    Args:
        raw: Raw API response (dict with pid as key)

    Returns:
        Tuple of (pokemon_data dict, pokemon_name str)
    """
    if isinstance(raw, dict) and len(raw) == 1:
        pid = list(raw.keys())[0]
        data = raw[pid]
        return data, data.get("name", "")
    elif isinstance(raw, dict) and len(raw) > 1:
        # Fallback: assume first entry
        pid = list(raw.keys())[0]
        data = raw[pid]
        return data, data.get("name", "")
    # Fallback for unexpected format
    return raw, getattr(raw, "name", "")


def _to_pokemon_data(pokemon: Any) -> dict[str, Any]:
    """Convert pokemon API response to PokemonData dict.

    The pokemon API returns {pid: pokemon_data}. This function
    extracts the inner pokemon_data and normalizes it.

    Args:
        pokemon: Raw pokemon API response

    Returns:
        PokemonData dict with normalized fields
    """
    data, _ = _extract_pokemon_data(pokemon)
    # Keep ASCII art as-is, no scaling to fixed size
    return {
        "id": _get_field(data, "id", 0),
        "name": _get_field(data, "name", ""),
        "ascii": _get_field(data, "ascii", ""),
        "type": _get_field(data, "type", []),
        "abilities": _get_field(data, "abilities", []),
        "height": _get_field(data, "height", 0.0),
        "weight": _get_field(data, "weight", 0.0),
        "link": _get_field(data, "link", ""),
    }


def lookup_pokemon_by_name(name: str) -> dict[str, Any] | None:
    """Look up Pokemon by exact name match (case-insensitive).

    Args:
        name: Pokemon name to look up

    Returns:
        PokemonData dict if found, None otherwise
    """
    try:
        pokemon = get_pokemon(name=name)
        if pokemon:
            return _to_pokemon_data(pokemon)
    except (Exception, SystemExit):
        # SystemExit is raised by pokemon package when Pokemon not found
        pass
    return None


def get_random_pokemon() -> dict[str, Any]:
    """Get a random Pokemon.

    Returns:
        PokemonData dict for a random Pokemon
    """
    pokemon = get_pokemon()
    return _to_pokemon_data(pokemon)


def deterministic_random_pick(agent_id: str, salt: str) -> tuple[dict[str, Any], str]:
    """Deterministically pick a Pokemon based on agent_id.

    Same agent_id + same salt always produces same Pokemon.
    Includes double fallback for robustness.

    Args:
        agent_id: Unique agent identifier
        salt: Salt string from config

    Returns:
        Tuple of (PokemonData dict, pokemon_name)
    """
    rng = mulberry32(hash_string(agent_id + salt))

    # mulberry32 returns [0, 1), int(rng() * 1000) is 0-999, +1 gives 1-1000
    pokemon_id = int(rng() * 1000) + 1

    try:
        raw = get_pokemon(pid=pokemon_id)
        data, name = _extract_pokemon_data(raw)
        return _to_pokemon_data(raw), name
    except Exception:
        pass

    # First fallback: try pid=1
    try:
        raw = get_pokemon(pid=1)
        data, name = _extract_pokemon_data(raw)
        return _to_pokemon_data(raw), name
    except Exception:
        pass

    # Second fallback: hard-coded data (should never reach here)
    return {
        "id": 1,
        "name": "Bulbasaur",
        "ascii": "",
        "type": ["grass", "poison"],
        "abilities": ["overgrow"],
        "height": 0.7,
        "weight": 6.9,
        "link": "",
    }, "Bulbasaur"
