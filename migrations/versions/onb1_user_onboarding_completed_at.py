"""onb1 — add users.onboarding_completed_at with backfill.

Persists onboarding completion server-side so clearing browser storage on any
device does not re-trigger the onboarding wizard. Existing users are backfilled
as already onboarded (they are active product users) so the new server flag
never forces them through onboarding again (#1471).

Revision ID: onb1_user_onboarding
Revises: cc2_card_privacy
Create Date: 2026-06-08

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "onb1_user_onboarding"
down_revision = "cc2_card_privacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_completed_at", sa.DateTime(), nullable=True),
    )
    # Backfill: every pre-existing user is treated as already onboarded.
    op.execute(
        "UPDATE users SET onboarding_completed_at = CURRENT_TIMESTAMP "
        "WHERE onboarding_completed_at IS NULL"
    )


def downgrade() -> None:
    bind = op.get_context().connection
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch:
            batch.drop_column("onboarding_completed_at")
        return

    op.drop_column("users", "onboarding_completed_at")
