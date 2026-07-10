"""Add Goal, immutable Harness Version, and Event tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_goal_harness_events"
down_revision: str | None = "0001_runtime_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=200), nullable=False),
        sa.Column("project_root", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.String(length=200), nullable=False),
        sa.Column("delivery_mode", sa.String(length=32), nullable=False),
        sa.Column("contract_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "harness_versions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "parent_version_id",
            sa.String(length=64),
            sa.ForeignKey("harness_versions.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("logical_ir_json", sa.JSON(), nullable=False),
        sa.Column("compilation_json", sa.JSON(), nullable=False),
        sa.Column("semantic_hash", sa.String(length=64), nullable=False),
        sa.Column("patch_reason", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("goal_id", "version"),
    )
    op.create_index("ix_harness_versions_goal_id", "harness_versions", ["goal_id"])
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_goal_id", "events", ["goal_id"])
    op.create_index("ix_events_correlation_id", "events", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_events_correlation_id", table_name="events")
    op.drop_index("ix_events_goal_id", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_harness_versions_goal_id", table_name="harness_versions")
    op.drop_table("harness_versions")
    op.drop_table("goals")
