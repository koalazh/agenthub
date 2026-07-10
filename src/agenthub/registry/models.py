from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_write: bool
    max_parallel_runs: int = Field(ge=1)


class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^(hermes|claude|codex)://[A-Za-z0-9_-]+$")
    runtime: Literal["hermes", "claude", "codex"]
    profile: str | None = None
    display_name: str | None = None
    enabled: bool = True
    capabilities: frozenset[str] = Field(min_length=1)
    constraints: AgentConstraints

    @model_validator(mode="after")
    def validate_runtime_identity(self) -> "AgentDefinition":
        if not self.id.startswith(f"{self.runtime}://"):
            raise ValueError("agent id scheme must match runtime")
        if self.runtime == "hermes" and not self.profile:
            raise ValueError("Hermes Agent requires a profile")
        if self.runtime != "hermes" and self.profile is not None:
            raise ValueError("only Hermes Agent definitions may set profile")
        return self


class AgentRegistryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agents: tuple[AgentDefinition, ...]

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "AgentRegistryConfig":
        ids = [agent.id for agent in self.agents]
        if len(set(ids)) != len(ids):
            raise ValueError("Agent Registry ids must be unique")
        return self
