"""Add Agent Registry snapshots and routing statistics."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_agent_registry"
down_revision: str | None = "0004_harness_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_definitions",
        sa.Column("id", sa.String(length=200), primary_key=True),
        sa.Column("runtime", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("constraints_json", sa.JSON(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "agent_stats",
        sa.Column(
            "agent_id",
            sa.String(length=200),
            sa.ForeignKey("agent_definitions.id"),
            primary_key=True,
        ),
        sa.Column("completed_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verifier_pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verifier_total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("average_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("average_latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recent_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("agent_stats")
    op.drop_table("agent_definitions")
