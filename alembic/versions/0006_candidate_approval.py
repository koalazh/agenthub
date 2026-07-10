"""Add candidate workspace facts and durable approvals."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_candidate_approval"
down_revision: str | None = "0005_agent_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("task_mappings") as batch:
        batch.add_column(sa.Column("workspace_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("branch_name", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("base_commit", sa.String(length=64), nullable=True))
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approvals_goal_id", "approvals", ["goal_id"])


def downgrade() -> None:
    op.drop_index("ix_approvals_goal_id", table_name="approvals")
    op.drop_table("approvals")
    with op.batch_alter_table("task_mappings") as batch:
        batch.drop_column("base_commit")
        batch.drop_column("branch_name")
        batch.drop_column("workspace_path")
