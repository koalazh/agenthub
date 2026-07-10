"""Add Handoff, Usage, and Goal Session links."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_coordination_observability"
down_revision: str | None = "0006_candidate_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "handoffs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("from_task_id", sa.String(length=100), nullable=False),
        sa.Column("to_task_id", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("goal_id", "from_task_id", "to_task_id"),
    )
    op.create_index("ix_handoffs_goal_id", "handoffs", ["goal_id"])
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("task_id", sa.String(length=100), nullable=False),
        sa.Column("run_id", sa.String(length=100), nullable=False),
        sa.Column("agent_id", sa.String(length=200), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_usage_records_goal_id", "usage_records", ["goal_id"])
    op.create_index("ix_usage_records_task_id", "usage_records", ["task_id"])
    op.create_index("ix_usage_records_run_id", "usage_records", ["run_id"])
    op.create_table(
        "goal_session_links",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("goal_id", sa.String(length=64), sa.ForeignKey("goals.id"), nullable=False),
        sa.Column("hermes_profile", sa.String(length=100), nullable=False),
        sa.Column("session_key", sa.String(length=300), nullable=False),
        sa.Column("channel", sa.String(length=64), nullable=False),
        sa.Column("external_user_id", sa.String(length=200), nullable=True),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("goal_id", "session_key", "relation"),
    )
    op.create_index("ix_goal_session_links_goal_id", "goal_session_links", ["goal_id"])
    op.create_index("ix_goal_session_links_session_key", "goal_session_links", ["session_key"])


def downgrade() -> None:
    op.drop_index("ix_goal_session_links_session_key", table_name="goal_session_links")
    op.drop_index("ix_goal_session_links_goal_id", table_name="goal_session_links")
    op.drop_table("goal_session_links")
    op.drop_index("ix_usage_records_run_id", table_name="usage_records")
    op.drop_index("ix_usage_records_task_id", table_name="usage_records")
    op.drop_index("ix_usage_records_goal_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("ix_handoffs_goal_id", table_name="handoffs")
    op.drop_table("handoffs")
