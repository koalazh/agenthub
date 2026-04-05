"""Real E2E Test - direct Python API calls with real LLM.

This test directly calls agenthub Python API functions to verify
the complete flow including real LLM API calls.

Run with: python test_e2e_real.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Set up environment from .env file
from dotenv import load_dotenv
load_dotenv()

# Ensure we're using the right model
os.environ.setdefault("MODEL_NAME", "anthropic:MiniMax-M2.7-highspeed")
os.environ.setdefault("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
os.environ.setdefault("ANTHROPIC_API_BASE", "https://api.minimaxi.com/anthropic")

import agenthub
from agenthub import init_agent, get_agent, list_agents, delete_agent
from agenthub.core.config import AgentHubConfig, get_config, set_config
from agenthub.core.types import InitAgentConfig, RawTranscriptInput
from agenthub.runtime.executor import SkillExecutor, set_executor


def cleanup_agenthub_dir():
    """Clean up test agenthub directory."""
    home_agenthub = Path.home() / ".agenthub_real_e2e"
    if home_agenthub.exists():
        import time
        # Retry a few times on Windows permission errors
        for _ in range(3):
            try:
                shutil.rmtree(home_agenthub)
                break
            except PermissionError:
                time.sleep(1)
    home_agenthub.mkdir(parents=True, exist_ok=True)
    return home_agenthub


def setup_executor():
    """Set up executor with real LLM."""
    model_name = os.environ.get("MODEL_NAME", "anthropic:MiniMax-M2.7-highspeed").strip()
    agenthub_dir = str(Path.home() / ".agenthub_real_e2e")
    executor = SkillExecutor(model=model_name, agenthub_dir=agenthub_dir)
    set_executor(executor)
    return executor


async def test_init_agent():
    """Test 1: Initialize a new agent with real LLM."""
    print("\n" + "=" * 60)
    print("TEST 1: Initialize Agent (Real LLM)")
    print("=" * 60)

    config = InitAgentConfig(
        name="real-e2e-agent",
        identity="A helpful coding assistant that specializes in Python",
        traits=["helpful", "python-expert", "clear-communicator"],
    )

    try:
        agent = await init_agent(config)
        print(f"[OK] Agent created successfully!")
        print(f"  ID: {agent.id}")
        print(f"  Name: {agent.name}")
        print(f"  Path: {agent.path}")

        # Check bootstrap files exist
        bootstrap_files = ["soul.md", "identity.md", "BOOTSTRAP.md"]
        for fname in bootstrap_files:
            fpath = agent.path / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8")
                print(f"  [OK] {fname} exists ({len(content)} bytes)")
            else:
                print(f"  [FAIL] {fname} MISSING!")
                return False

        return True
    except Exception as e:
        print(f"[FAIL] Failed to initialize agent: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_evolution_with_llm():
    """Test 2: Run evolution with real LLM."""
    print("\n" + "=" * 60)
    print("TEST 2: Evolution (Real LLM)")
    print("=" * 60)

    from agenthub.core.config import get_config
    config = get_config()
    import subprocess

    # Create a minimal agent directory manually for evolution testing
    agent_id = f"evo-test-{int(datetime.now().timestamp())}"
    agent_dir = config.agenthub_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "skills" / "builtin").mkdir(parents=True, exist_ok=True)
    (agent_dir / "memory" / "projects" / "universal").mkdir(parents=True, exist_ok=True)
    (agent_dir / "archives").mkdir()

    # Create bootstrap files
    (agent_dir / "soul.md").write_text("You are a helpful coding assistant.", encoding="utf-8")
    (agent_dir / "identity.md").write_text("I help with coding tasks.", encoding="utf-8")
    (agent_dir / "BOOTSTRAP.md").write_text("Always write tests first.", encoding="utf-8")

    # Create evolution skill
    (agent_dir / "skills" / "builtin" / "evolution.md").write_text(
        "# Evolution Skill\nRecord insights from conversations.",
        encoding="utf-8",
    )

    # Git init
    subprocess.run(["git", "init"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=agent_dir, capture_output=True, check=True)
    print(f"[OK] Created test agent at {agent_dir}")

    transcript = RawTranscriptInput(
        id="test-transcript-001",
        content="""Today I helped debug a tricky race condition in a multi-threaded Python application.
The issue was that two threads were accessing a shared dictionary simultaneously without proper locking.
I used Python's threading.Lock() to synchronize access and added a context manager for clean acquisition.
The fix involved wrapping the critical section with 'with self._lock:' pattern.
This is a common pattern that should be documented as a skill.

Key insights:
1. Always use lock when accessing shared mutable state
2. Context manager (with statement) ensures proper lock release
3. Never hold locks for longer than necessary
4. Document which resources need protection""",
        project_id="debugging-project",
        metadata={"session_id": "abc123", "language": "python"},
    )

    try:
        result = await agenthub.evolution(agent_id, transcript)
        print(f"[OK] Evolution completed!")
        print(f"  Should record: {result.should_record}")
        print(f"  Form: {result.form}")
        print(f"  Scope: {result.scope}")
        print(f"  Confidence: {result.confidence}")
        if result.skill_name:
            print(f"  Skill name: {result.skill_name}")
        if result.skip_reason:
            print(f"  Skip reason: {result.skip_reason}")
        if result.content:
            print(f"  Content preview: {result.content[:100]}...")
        if result.commit_hash:
            print(f"  Commit hash: {result.commit_hash}")

        # Verify archive was created
        archives_dir = agent_dir / "archives"
        archives = list(archives_dir.glob("*.json"))
        print(f"  Archives created: {len(archives)}")

        return True
    except Exception as e:
        print(f"[FAIL] Evolution failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_self_evolution_with_llm():
    """Test 3: Run self-evolution with real LLM."""
    print("\n" + "=" * 60)
    print("TEST 3: Self Evolution (Real LLM)")
    print("=" * 60)

    # Create agent directory manually to skip init-agent LLM call
    from agenthub.core.config import get_config
    config = get_config()
    import subprocess

    agent_id = f"self-evo-test-{int(datetime.now().timestamp())}"
    agent_dir = config.agenthub_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "skills" / "builtin").mkdir(parents=True, exist_ok=True)
    (agent_dir / "skills" / "universal").mkdir(parents=True, exist_ok=True)
    (agent_dir / "skills" / "projects").mkdir(parents=True, exist_ok=True)
    (agent_dir / "memory" / "projects" / "universal").mkdir(parents=True, exist_ok=True)
    (agent_dir / "archives").mkdir()

    # Create bootstrap files
    (agent_dir / "soul.md").write_text("You are a helpful coding assistant.", encoding="utf-8")
    (agent_dir / "identity.md").write_text("I help with coding tasks.", encoding="utf-8")
    (agent_dir / "BOOTSTRAP.md").write_text("Always write tests first.", encoding="utf-8")

    # Create self-evolution skill
    (agent_dir / "skills" / "builtin" / "self-evolution.md").write_text(
        "# Self-Evolution Skill\nAnalyze and improve agent behavior.",
        encoding="utf-8",
    )

    # Git init
    subprocess.run(["git", "init"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=agent_dir, capture_output=True, check=True)
    print(f"[OK] Created test agent at {agent_dir}")

    try:
        result = await agenthub.self_evolution(agent_id)
        print(f"[OK] Self-evolution completed!")
        print(f"  Has changes: {result.has_changes}")
        print(f"  Changes count: {len(result.changes)}")
        return True
    except Exception as e:
        print(f"[FAIL] Self-evolution failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_preflight_check_llm():
    """Test 4: Run pre-flight check with real LLM."""
    print("\n" + "=" * 60)
    print("TEST 4: Pre-Flight Check (Real LLM)")
    print("=" * 60)

    from agenthub.core.config import get_config
    config = get_config()
    import subprocess

    # Create agent directory manually
    agent_id = f"preflight-test-{int(datetime.now().timestamp())}"
    agent_dir = config.agenthub_dir / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "skills" / "builtin").mkdir(parents=True, exist_ok=True)
    (agent_dir / "memory" / "projects" / "universal").mkdir(parents=True, exist_ok=True)
    (agent_dir / "archives").mkdir()

    # Create bootstrap files
    (agent_dir / "soul.md").write_text("You are a helpful coding assistant.", encoding="utf-8")
    (agent_dir / "identity.md").write_text("I help with coding tasks.", encoding="utf-8")
    (agent_dir / "BOOTSTRAP.md").write_text("Always write tests first.", encoding="utf-8")

    # Create evolution skill
    (agent_dir / "skills" / "builtin" / "evolution.md").write_text(
        "# Evolution Skill\nRecord insights from conversations.",
        encoding="utf-8",
    )

    # Git init
    subprocess.run(["git", "init"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=agent_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=agent_dir, capture_output=True, check=True)
    print(f"[OK] Created test agent at {agent_dir}")

    # Test evolution with info that should be skipped
    transcript = RawTranscriptInput(
        id="test-deriv-001",
        content="Python is a programming language. It has dynamic typing and garbage collection.",
        project_id=None,
        metadata={"session_id": "abc123", "language": "python"},
    )

    try:
        result = await agenthub.evolution(agent_id, transcript)
        print(f"[OK] Evolution completed!")
        print(f"  Should record: {result.should_record}")
        if result.skip_reason:
            print(f"  Skip reason: {result.skip_reason}")
        if result.should_record:
            print(f"  [FAIL] Pre-Flight Check did not skip derivable info")
            return False
        print(f"  [OK] Pre-Flight Check correctly skipped derivable info")
        return True
    except Exception as e:
        print(f"[FAIL] Pre-Flight Check failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all E2E tests."""
    print("============================================================")
    print("Real E2E Test with Real LLM API")
    print("============================================================")
    print(f"API Base: {os.environ.get('ANTHROPIC_API_BASE')}")
    print(f"Model: {os.environ.get('MODEL_NAME')}")

    # Setup config and executor
    agenthub_dir = cleanup_agenthub_dir()
    print(f"Using agenthub_dir: {agenthub_dir}")

    config = AgentHubConfig(agenthub_dir=agenthub_dir)
    set_config(config)
    setup_executor()

    results = {}

    # Run all tests
    results["init"] = await test_init_agent()
    results["evolution"] = await test_evolution_with_llm()
    results["self_evolution"] = await test_self_evolution_with_llm()
    results["preflight"] = await test_preflight_check_llm()

    # Summary
    print("\n" + "=" * 60)
    print("REAL E2E TEST SUMMARY")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "[OK] PASS" if passed else "[FAIL] FAIL"
        print(f"  {test_name}: {status}")

    all_passed = all(results.values())
    print("\n" + ("=" * 60))
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
