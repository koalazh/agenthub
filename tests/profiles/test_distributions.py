import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HERMES_SOURCE = Path(
    os.environ.get("HERMES_SOURCE_PATH", "/Users/koala/work/hermes-agent")
)


@pytest.mark.skipif(not HERMES_SOURCE.is_dir(), reason="Hermes source checkout unavailable")
def test_profile_manifests_are_accepted_by_pinned_hermes() -> None:
    sys.path.insert(0, str(HERMES_SOURCE))
    from hermes_cli.profile_distribution import read_manifest

    hub = read_manifest(ROOT / "profiles" / "agenthub-hub")
    reviewer = read_manifest(ROOT / "profiles" / "hermes-reviewer")

    assert hub is not None and hub.name == "agenthub-hub"
    assert reviewer is not None and reviewer.name == "hermes-reviewer"


def test_hub_distribution_declares_agenthub_mcp_server() -> None:
    config = json.loads((ROOT / "profiles" / "agenthub-hub" / "mcp.json").read_text())

    assert config["servers"]["agenthub"]["command"] == "agenthub"
    assert config["servers"]["agenthub"]["args"] == ["mcp-server"]


def test_profiles_do_not_ship_credentials_or_memory() -> None:
    forbidden = {".env", "auth.json", "MEMORY.md", "state.db"}

    for profile in (ROOT / "profiles").iterdir():
        assert not (forbidden & {path.name for path in profile.rglob("*")})
