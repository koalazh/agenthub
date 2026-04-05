"""Tests for Pokemon Companion feature - Phase 1 Pokemon data layer."""

import json
import pytest
from unittest.mock import MagicMock, patch

from agenthub.core.companion import get_personality, get_pokemon_avatar
from agenthub.core.errors import NotFoundError, ValidationError
from agenthub.core.pokemon_db import (
    deterministic_random_pick,
    get_random_pokemon,
    hash_string,
    lookup_pokemon_by_name,
    mulberry32,
)
from agenthub.core.types import InitAgentConfig, PokemonData


class TestPokemonLookup:
    """Test Pokemon lookup functionality."""

    def test_lookup_pikachu(self) -> None:
        """Test looking up Pikachu by name."""
        result = lookup_pokemon_by_name("Pikachu")
        assert result is not None
        assert result["id"] == 25
        assert result["name"] == "Pikachu"
        assert result["type"] == ["electric"]

    def test_lookup_case_insensitive(self) -> None:
        """Test that lookup is case-insensitive."""
        result = lookup_pokemon_by_name("PIKACHU")
        assert result is not None
        assert result["id"] == 25

        result2 = lookup_pokemon_by_name("pikachu")
        assert result2 is not None
        assert result2["id"] == 25

    def test_lookup_not_found(self) -> None:
        """Test looking up non-existent Pokemon returns None."""
        result = lookup_pokemon_by_name("NonExistentPokemon12345")
        assert result is None

    def test_lookup_returns_valid_data(self) -> None:
        """Test that lookup returns complete PokemonData."""
        result = lookup_pokemon_by_name("Bulbasaur")
        assert result is not None
        # Check all required fields exist
        assert "id" in result
        assert "name" in result
        assert "ascii" in result
        assert "type" in result
        assert "abilities" in result
        assert "height" in result
        assert "weight" in result
        assert "link" in result


class TestPRNG:
    """Test PRNG functionality."""

    def test_mulberry32_returns_float(self) -> None:
        """Test that mulberry32 returns floats in [0, 1)."""
        rng = mulberry32(12345)
        result = rng()
        assert isinstance(result, float)
        assert 0.0 <= result < 1.0

    def test_mulberry32_deterministic(self) -> None:
        """Test that mulberry32 is deterministic."""
        rng1 = mulberry32(42)
        rng2 = mulberry32(42)
        assert rng1() == rng2()
        assert rng1() == rng2()

    def test_mulberry32_different_seeds(self) -> None:
        """Test that different seeds produce different sequences."""
        rng1 = mulberry32(1)
        rng2 = mulberry32(2)
        assert rng1() != rng2()

    def test_seed_zero_no_fixed_output(self) -> None:
        """Test that seed=0 does not produce fixed output.

        The mulberry32 PRNG has a guard that sets a=0x6D2B79F5
        when seed=0 to prevent the first roll from returning 0.
        We verify by calling rng() twice - if the guard failed,
        the second call might also return 0.
        """
        rng = mulberry32(0)
        first = rng()
        second = rng()
        # First should not be 0 (guard activates)
        assert first != 0.0, "seed=0 guard failed: first roll is 0"
        # Second should also not be 0 (mathematically unlikely after guard)
        assert second != 0.0, "seed=0 guard partially failed: second roll is 0"
        # They should be different
        assert first != second, "seed=0 produced same value twice"


class TestHashString:
    """Test FNV-1a hash function."""

    def test_hash_string_returns_int(self) -> None:
        """Test that hash_string returns an integer."""
        result = hash_string("test")
        assert isinstance(result, int)

    def test_hash_string_deterministic(self) -> None:
        """Test that hash_string is deterministic."""
        h1 = hash_string("hello")
        h2 = hash_string("hello")
        assert h1 == h2

    def test_hash_string_different_inputs(self) -> None:
        """Test that different inputs produce different hashes."""
        h1 = hash_string("hello")
        h2 = hash_string("world")
        assert h1 != h2

    def test_hash_string_empty_string(self) -> None:
        """Test hashing empty string."""
        result = hash_string("")
        assert isinstance(result, int)
        assert result > 0


class TestDeterministicRandomPick:
    """Test deterministic Pokemon selection."""

    def test_same_agent_id_same_pokemon(self) -> None:
        """Test that same agent_id + salt produces same Pokemon."""
        pokemon1, name1 = deterministic_random_pick("agent-123", "salt-abc")
        pokemon2, name2 = deterministic_random_pick("agent-123", "salt-abc")

        assert pokemon1["id"] == pokemon2["id"]
        assert name1 == name2
        assert pokemon1["name"] == pokemon2["name"]

    def test_different_agent_id_different_pokemon(self) -> None:
        """Test that different agent_ids produce different Pokemon."""
        pokemon1, name1 = deterministic_random_pick("agent-123", "salt-abc")
        pokemon2, name2 = deterministic_random_pick("agent-456", "salt-abc")

        # Note: This is probabilistic - different seeds should give different
        # results, but there's a tiny chance they could match
        assert pokemon1["id"] != pokemon2["id"]

    def test_different_salt_different_pokemon(self) -> None:
        """Test that different salts produce different Pokemon."""
        pokemon1, name1 = deterministic_random_pick("agent-123", "salt-abc")
        pokemon2, name2 = deterministic_random_pick("agent-123", "salt-xyz")

        assert pokemon1["id"] != pokemon2["id"]

    def test_returns_valid_pokemon_data(self) -> None:
        """Test that returned Pokemon has all required fields."""
        pokemon, name = deterministic_random_pick("agent-123", "salt-abc")

        assert "id" in pokemon
        assert "name" in pokemon
        assert "ascii" in pokemon
        assert "type" in pokemon
        assert "abilities" in pokemon
        assert pokemon["name"] == name

    def test_pokemon_id_in_valid_range(self) -> None:
        """Test that Pokemon ID is in valid range (1-1000+)."""
        for _ in range(10):
            pokemon, _ = deterministic_random_pick("agent-test", "salt")
            # Pokemon ID should be positive
            assert pokemon["id"] >= 1


class TestGetRandomPokemon:
    """Test random Pokemon selection."""

    def test_get_random_pokemon_returns_valid_data(self) -> None:
        """Test that get_random_pokemon returns complete data."""
        result = get_random_pokemon()

        assert "id" in result
        assert "name" in result
        assert "ascii" in result
        assert "type" in result
        assert "abilities" in result
        assert result["id"] >= 1

    def test_get_random_pokemon_not_empty_ascii(self) -> None:
        """Test that ASCII art is not empty (default is spaces)."""
        result = get_random_pokemon()
        # ASCII should not be empty string
        assert len(result["ascii"]) > 0


class TestGetPokemonAvatar:
    """Test get_pokemon_avatar function (Phase 2)."""

    def test_user_name_exact_match(self) -> None:
        """Test user provided name matches Pokemon exactly."""
        pokemon, name = get_pokemon_avatar("agent-123", "Pikachu")
        assert name == "Pikachu"
        assert pokemon.name == "Pikachu"
        assert pokemon.id == 25

    def test_user_name_no_match(self) -> None:
        """Test user provided name does not match any Pokemon."""
        pokemon, name = get_pokemon_avatar("agent-123", "MyCustomName")
        # User name should be preserved
        assert name == "MyCustomName"
        # But we get a random Pokemon
        assert pokemon.id >= 1

    def test_no_name_deterministic_random(self) -> None:
        """Test no name provided returns deterministic random Pokemon."""
        p1, n1 = get_pokemon_avatar("agent-123", None)
        p2, n2 = get_pokemon_avatar("agent-123", None)
        # Same agent_id should give same result
        assert p1.id == p2.id
        assert n1 == n2

    def test_no_name_deterministic_different_agents(self) -> None:
        """Test different agent_ids produce different Pokemon."""
        p1, n1 = get_pokemon_avatar("agent-123", None)
        p2, n2 = get_pokemon_avatar("agent-456", None)
        # Different agents should (likely) get different Pokemon
        assert p1.id != p2.id

    def test_returns_pokemon_data_object(self) -> None:
        """Test that get_pokemon_avatar returns PokemonData object."""
        pokemon, name = get_pokemon_avatar("agent-123", "Pikachu")
        assert isinstance(pokemon, PokemonData)
        assert pokemon.name == "Pikachu"


class TestGetPersonality:
    """Test get_personality passthrough function (Phase 2)."""

    def test_personality_user_override(self) -> None:
        """Test user provided personality is passed through."""
        personality = "friendly, helpful, curious"
        result = get_personality(personality)
        assert result == personality

    def test_personality_none(self) -> None:
        """Test None personality returns None."""
        result = get_personality(None)
        assert result is None


class TestPokemonDataModel:
    """Test PokemonData model (Phase 2)."""

    def test_pokemon_data_creation(self) -> None:
        """Test PokemonData model can be created."""
        data = {
            "id": 25,
            "name": "Pikachu",
            "ascii": "@" * 60,
            "type": ["electric"],
            "abilities": ["static"],
            "height": 0.4,
            "weight": 6.0,
            "link": "http://example.com",
        }
        pokemon = PokemonData(**data)
        assert pokemon.id == 25
        assert pokemon.name == "Pikachu"
        assert pokemon.type == ["electric"]

    def test_pokemon_data_defaults(self) -> None:
        """Test PokemonData default values for optional fields."""
        # Only required fields are id and name
        data = {"id": 1, "name": "Test", "ascii": "test"}
        pokemon = PokemonData(**data)
        # Optional fields have defaults
        assert pokemon.type == []
        assert pokemon.abilities == []
        assert pokemon.height == 0.0
        assert pokemon.weight == 0.0
        assert pokemon.link == ""

    def test_pokemon_data_ascii_normalization(self) -> None:
        """Test PokemonData normalizes empty ASCII to spaces."""
        data = {"id": 1, "name": "Test", "ascii": ""}
        pokemon = PokemonData(**data)
        assert len(pokemon.ascii) > 0


class TestInitAgentConfigUpdate:
    """Test InitAgentConfig updated for optional name/personality (Phase 2)."""

    def test_name_optional(self) -> None:
        """Test name is now optional."""
        config = InitAgentConfig(
            identity="An assistant",
        )
        assert config.name is None

    def test_personality_optional(self) -> None:
        """Test personality is now optional."""
        config = InitAgentConfig(
            identity="An assistant",
        )
        assert config.personality is None

    def test_name_with_value(self) -> None:
        """Test name with value works."""
        config = InitAgentConfig(
            name="test-agent",
            identity="An assistant",
        )
        assert config.name == "test-agent"

    def test_personality_with_value(self) -> None:
        """Test personality with value works."""
        config = InitAgentConfig(
            name="test-agent",
            personality="friendly",
            identity="An assistant",
        )
        assert config.personality == "friendly"

    def test_name_truncation(self) -> None:
        """Test name is truncated to 50 chars."""
        long_name = "a" * 100
        config = InitAgentConfig(
            name=long_name,
            identity="An assistant",
        )
        assert len(config.name) == 50

    def test_personality_truncation(self) -> None:
        """Test personality is truncated to 500 chars."""
        long_personality = "b" * 600
        config = InitAgentConfig(
            name="test",
            personality=long_personality,
            identity="An assistant",
        )
        assert len(config.personality) == 500
