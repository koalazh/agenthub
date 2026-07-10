"""Add provenance-bearing Artifact metadata."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_artifacts"
down_revision: str | None = "0002_goal_harness_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=False),
        sa.Column("run_id", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("media_type", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by_agent", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_goal_id", "artifacts", ["goal_id"])
    op.create_index("ix_artifacts_task_id", "artifacts", ["task_id"])
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_artifacts_run_id", table_name="artifacts")
    op.drop_index("ix_artifacts_task_id", table_name="artifacts")
    op.drop_index("ix_artifacts_goal_id", table_name="artifacts")
    op.drop_table("artifacts")
