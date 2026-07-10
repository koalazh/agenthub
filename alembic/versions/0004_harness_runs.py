"""Add recoverable Harness Runs, Step Executions, and Kanban mappings."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_harness_runs"
down_revision: str | None = "0003_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "harness_runs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column(
            "harness_version_id",
            sa.String(length=64),
            sa.ForeignKey("harness_versions.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_phase", sa.String(length=100), nullable=True),
        sa.Column("checkpoint_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_harness_runs_goal_id", "harness_runs", ["goal_id"])
    op.create_index(
        "ix_harness_runs_harness_version_id", "harness_runs", ["harness_version_id"]
    )
    op.create_table(
        "step_executions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "harness_run_id",
            sa.String(length=64),
            sa.ForeignKey("harness_runs.id"),
            nullable=False,
        ),
        sa.Column("step_id", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("kanban_task_id", sa.String(length=100), nullable=True),
        sa.Column("agent_id", sa.String(length=200), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("harness_run_id", "step_id", "attempt"),
    )
    op.create_index(
        "ix_step_executions_harness_run_id", "step_executions", ["harness_run_id"]
    )
    op.create_table(
        "task_mappings",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column(
            "harness_version_id",
            sa.String(length=64),
            sa.ForeignKey("harness_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "harness_run_id",
            sa.String(length=64),
            sa.ForeignKey("harness_runs.id"),
            nullable=False,
        ),
        sa.Column("step_id", sa.String(length=100), nullable=False),
        sa.Column("kanban_board", sa.String(length=64), nullable=False),
        sa.Column("kanban_task_id", sa.String(length=100), nullable=False, unique=True),
        sa.Column("expected_run_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("harness_run_id", "step_id"),
    )
    op.create_index("ix_task_mappings_goal_id", "task_mappings", ["goal_id"])
    op.create_index(
        "ix_task_mappings_harness_run_id", "task_mappings", ["harness_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_task_mappings_harness_run_id", table_name="task_mappings")
    op.drop_index("ix_task_mappings_goal_id", table_name="task_mappings")
    op.drop_table("task_mappings")
    op.drop_index("ix_step_executions_harness_run_id", table_name="step_executions")
    op.drop_table("step_executions")
    op.drop_index("ix_harness_runs_harness_version_id", table_name="harness_runs")
    op.drop_index("ix_harness_runs_goal_id", table_name="harness_runs")
    op.drop_table("harness_runs")
