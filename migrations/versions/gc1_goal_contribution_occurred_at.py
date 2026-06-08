"""gc1 — add goal_contributions.occurred_at.

Adds a user-facing contribution date (may be back-dated by the client) to the
goal contribution history. Backfills existing rows from created_at so the
column can be NOT NULL. created_at stays as the immutable audit timestamp
(#1470).

Revision ID: gc1_goal_contrib_date
Revises: onb1_user_onboarding
Create Date: 2026-06-08

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "gc1_goal_contrib_date"
down_revision = "onb1_user_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add as nullable first so existing rows can be backfilled, then enforce
    # NOT NULL (works on both PostgreSQL and SQLite via batch).
    op.add_column(
        "goal_contributions",
        sa.Column("occurred_at", sa.Date(), nullable=True),
    )
    op.execute(
        "UPDATE goal_contributions "
        "SET occurred_at = CAST(created_at AS DATE) "
        "WHERE occurred_at IS NULL"
    )
    bind = op.get_context().connection
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("goal_contributions") as batch:
            batch.alter_column("occurred_at", existing_type=sa.Date(), nullable=False)
    else:
        op.alter_column("goal_contributions", "occurred_at", nullable=False)


def downgrade() -> None:
    bind = op.get_context().connection
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("goal_contributions") as batch:
            batch.drop_column("occurred_at")
        return

    op.drop_column("goal_contributions", "occurred_at")
