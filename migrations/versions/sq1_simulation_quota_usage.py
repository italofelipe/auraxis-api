"""add simulation_quota_usage table (freemium simulador) — #1409

Revision ID: sq1_simulation_quota_usage
Revises: fb1_ai_insight_feedback
Create Date: 2026-05-31

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "sq1_simulation_quota_usage"
down_revision = "fb1_ai_insight_feedback"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    """Return True when *name* already exists in the database."""
    inspector = sa.inspect(op.get_context().connection)
    return name in inspector.get_table_names()


def upgrade() -> None:
    # Idempotent: skip if prod drift already created this table (reconciliation).
    if _has_table("simulation_quota_usage"):
        return

    op.create_table(
        "simulation_quota_usage",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "period", name="uq_simulation_quota_user_period"
        ),
    )
    op.create_index(
        "ix_simulation_quota_usage_user_id",
        "simulation_quota_usage",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_simulation_quota_usage_user_id", table_name="simulation_quota_usage"
    )
    op.drop_table("simulation_quota_usage")
