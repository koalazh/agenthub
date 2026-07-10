from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTHUB_",
        env_file=".env",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = Path("~/.agenthub")
    database_url: str = "sqlite:///~/.agenthub/agenthub.db"
    hermes_api_base_url: str = "http://127.0.0.1:8642"
    hermes_source_path: Path | None = None
    hermes_kanban_home: Path = Path("~/.hermes")
    hermes_probe_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    agent_registry_path: Path = Path("config/agents.yaml")
    default_worker_lane: str = Field(default="fake", pattern=r"^(fake|hermes|claude|codex)$")

    @field_validator(
        "data_dir",
        "hermes_source_path",
        "hermes_kanban_home",
        "agent_registry_path",
        mode="after",
    )
    @classmethod
    def expand_path(cls, value: Path | None) -> Path | None:
        return value.expanduser().resolve() if value is not None else None

    @field_validator("database_url", mode="after")
    @classmethod
    def expand_sqlite_url(cls, value: str) -> str:
        prefix = "sqlite:///"
        if value.startswith(prefix):
            path = Path(value.removeprefix(prefix)).expanduser()
            return f"{prefix}{path.resolve()}"
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
