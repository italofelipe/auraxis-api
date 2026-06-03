"""ai_insight_feedback

Creates the `ai_insight_feedback` table (#1387): per-user rating (0–5 on
relevance/truthfulness/depth/usefulness) + free-text comment on a generated
AI insight. One row per (user, insight). CASCADE on insight/user deletion.

Revision ID: fb1_ai_insight_feedback
Revises: rec1_recurrence_cadence
Create Date: 2026-05-31 00:00:00.000000

Refs: #1387 (auraxis-api).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "fb1_ai_insight_feedback"
down_revision = "rec1_recurrence_cadence"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    """Return True when *name* already exists in the database."""
    inspector = sa.inspect(op.get_context().connection)
    return name in inspector.get_table_names()


def upgrade() -> None:
    # Idempotent: skip if prod drift already created this table (reconciliation).
    if _has_table("ai_insight_feedback"):
        return

    op.create_table(
        "ai_insight_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "insight_id",
            UUID(as_uuid=True),
            sa.ForeignKey("ai_insights.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relevance", sa.Integer(), nullable=False),
        sa.Column("truthfulness", sa.Integer(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("usefulness", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "insight_id", name="uq_ai_insight_feedback_user_insight"
        ),
        sa.CheckConstraint(
            "relevance BETWEEN 0 AND 5 AND truthfulness BETWEEN 0 AND 5 "
            "AND depth BETWEEN 0 AND 5 AND usefulness BETWEEN 0 AND 5",
            name="ck_ai_insight_feedback_rating_range",
        ),
    )
    op.create_index(
        "ix_ai_insight_feedback_insight_id", "ai_insight_feedback", ["insight_id"]
    )
    op.create_index(
        "ix_ai_insight_feedback_user_id", "ai_insight_feedback", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_insight_feedback_user_id", table_name="ai_insight_feedback")
    op.drop_index("ix_ai_insight_feedback_insight_id", table_name="ai_insight_feedback")
    op.drop_table("ai_insight_feedback")
