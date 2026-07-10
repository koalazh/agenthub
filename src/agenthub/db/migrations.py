from pathlib import Path

from alembic.config import Config

from alembic import command


def upgrade_database(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        database_path = Path(database_url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parents[3]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
