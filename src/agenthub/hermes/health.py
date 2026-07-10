import asyncio
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import httpx


def detect_hermes_installation(source_path: Path | None) -> dict[str, Any]:
    executable = shutil.which("hermes")
    if executable:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        version = (result.stdout or result.stderr).strip() or None
        return {
            "status": "ok" if result.returncode == 0 else "degraded",
            "kind": "cli",
            "path": executable,
            "version": version,
        }

    if source_path is not None:
        pyproject = source_path / "pyproject.toml"
        kanban = source_path / "hermes_cli" / "kanban_db.py"
        if pyproject.is_file() and kanban.is_file():
            with pyproject.open("rb") as file:
                version = tomllib.load(file).get("project", {}).get("version")
            return {
                "status": "ok",
                "kind": "source",
                "path": str(source_path),
                "version": version,
            }

    return {
        "status": "unavailable",
        "kind": None,
        "path": None,
        "version": None,
        "detail": "Hermes CLI is not on PATH and no compatible source checkout is configured",
    }


async def probe_hermes_api(base_url: str, timeout_seconds: float) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            health, detailed = await asyncio.gather(
                client.get(f"{base_url.rstrip('/')}/health"),
                client.get(f"{base_url.rstrip('/')}/health/detailed"),
            )
        health.raise_for_status()
        detailed.raise_for_status()
        payload = health.json()
        detail_payload = detailed.json()
        return {
            "status": "ok",
            "api": payload,
            "gateway": {
                "status": detail_payload.get("gateway_state") or "unknown",
                "platforms": detail_payload.get("platforms", {}),
                "pid": detail_payload.get("pid"),
            },
        }
    except (httpx.HTTPError, ValueError) as exc:
        return {"status": "unavailable", "detail": str(exc)}


def inspect_kanban(hermes_home: Path, installation: dict[str, Any]) -> dict[str, Any]:
    kanban_root = hermes_home / "kanban"
    board_root = kanban_root / "boards"
    databases = list(board_root.glob("*/kanban.db")) if board_root.is_dir() else []
    return {
        "status": "ok" if installation["status"] == "ok" else "unavailable",
        "kernel_available": installation["status"] == "ok",
        "home": str(kanban_root),
        "initialized": kanban_root.is_dir(),
        "board_databases": len(databases),
    }


async def hermes_health(
    *,
    source_path: Path | None,
    api_base_url: str,
    kanban_home: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    installation = detect_hermes_installation(source_path)
    return {
        "installation": installation,
        "api_gateway": await probe_hermes_api(api_base_url, timeout_seconds),
        "kanban": inspect_kanban(kanban_home, installation),
    }
