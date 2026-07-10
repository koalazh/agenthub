from pathlib import Path

from fastapi.testclient import TestClient

from agenthub.api.app import create_app
from agenthub.settings import Settings


def test_health_initializes_database(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'agenthub.db'}",
        hermes_api_base_url="http://127.0.0.1:1",
        hermes_probe_timeout_seconds=0.1,
    )

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert (tmp_path / "agenthub.db").is_file()


def test_detailed_health_reports_unavailable_hermes(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'agenthub.db'}",
        hermes_api_base_url="http://127.0.0.1:1",
        hermes_source_path=tmp_path / "missing-hermes",
        hermes_probe_timeout_seconds=0.1,
    )

    with TestClient(create_app(settings)) as client:
        payload = client.get("/health/detailed").json()

    assert payload["database"]["status"] == "ok"
    assert payload["hermes"]["installation"]["status"] == "unavailable"
    assert payload["hermes"]["api_gateway"]["status"] == "unavailable"
    assert payload["hermes"]["kanban"]["status"] == "unavailable"
