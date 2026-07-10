from pathlib import Path

from agenthub.hermes.health import detect_hermes_installation, inspect_kanban


def test_detects_compatible_hermes_source(tmp_path: Path) -> None:
    (tmp_path / "hermes_cli").mkdir()
    (tmp_path / "hermes_cli" / "kanban_db.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "hermes-agent"\nversion = "0.14.0"\n',
        encoding="utf-8",
    )

    result = detect_hermes_installation(tmp_path)

    assert result["status"] == "ok"
    assert result["kind"] == "source"
    assert result["version"] == "0.14.0"


def test_kanban_health_counts_initialized_board_databases(tmp_path: Path) -> None:
    board = tmp_path / "kanban" / "boards" / "agenthub-demo"
    board.mkdir(parents=True)
    (board / "kanban.db").touch()

    result = inspect_kanban(tmp_path, {"status": "ok"})

    assert result["status"] == "ok"
    assert result["initialized"] is True
    assert result["board_databases"] == 1
