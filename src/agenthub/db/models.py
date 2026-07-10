from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agenthub.db.base import Base


class GoalRecord(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(200), nullable=False)
    project_root: Mapped[str] = mapped_column(Text, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    delivery_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    harness_versions: Mapped[list["HarnessVersionRecord"]] = relationship(
        back_populates="goal", order_by="HarnessVersionRecord.version"
    )


class HarnessVersionRecord(Base):
    __tablename__ = "harness_versions"
    __table_args__ = (UniqueConstraint("goal_id", "version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("harness_versions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    logical_ir_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    compilation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    semantic_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    patch_reason: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    goal: Mapped[GoalRecord] = relationship(back_populates="harness_versions")


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by_agent: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class HarnessRunRecord(Base):
    __tablename__ = "harness_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), nullable=False, index=True)
    harness_version_id: Mapped[str] = mapped_column(
        ForeignKey("harness_versions.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_phase: Mapped[str | None] = mapped_column(String(100), nullable=True)
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StepExecutionRecord(Base):
    __tablename__ = "step_executions"
    __table_args__ = (UniqueConstraint("harness_run_id", "step_id", "attempt"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    harness_run_id: Mapped[str] = mapped_column(
        ForeignKey("harness_runs.id"), nullable=False, index=True
    )
    step_id: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    kanban_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class TaskMappingRecord(Base):
    __tablename__ = "task_mappings"
    __table_args__ = (UniqueConstraint("harness_run_id", "step_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    goal_id: Mapped[str] = mapped_column(ForeignKey("goals.id"), nullable=False, index=True)
    harness_version_id: Mapped[str] = mapped_column(
        ForeignKey("harness_versions.id"), nullable=False
    )
    harness_run_id: Mapped[str] = mapped_column(
        ForeignKey("harness_runs.id"), nullable=False, index=True
    )
    step_id: Mapped[str] = mapped_column(String(100), nullable=False)
    kanban_board: Mapped[str] = mapped_column(String(64), nullable=False)
    kanban_task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    expected_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AgentDefinitionRecord(Base):
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    runtime: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    constraints_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class AgentStatsRecord(Base):
    __tablename__ = "agent_stats"

    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agent_definitions.id"), primary_key=True
    )
    completed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verifier_pass_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    verifier_total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    average_cost: Mapped[float] = mapped_column(nullable=False, default=0.0)
    average_latency_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    recent_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
