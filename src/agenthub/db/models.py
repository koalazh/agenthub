from datetime import datetime
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
