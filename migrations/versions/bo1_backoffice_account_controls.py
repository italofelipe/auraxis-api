"""Add backoffice account controls and premium overrides.

Revision ID: bo1_account_controls
Revises: sae1_sharing_audit_events
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "bo1_account_controls"
down_revision = "sae1_sharing_audit_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("blocked_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("blocked_reason", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("blocked_by", sa.String(128), nullable=True))
    op.create_table(
        "premium_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.String(128), nullable=False),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("revoked_by", sa.String(128), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_premium_overrides_user_id"),
    )
    op.create_index(
        "ix_premium_overrides_user_id",
        "premium_overrides",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_premium_overrides_user_id", table_name="premium_overrides")
    op.drop_table("premium_overrides")
    op.drop_column("users", "blocked_by")
    op.drop_column("users", "blocked_reason")
    op.drop_column("users", "blocked_at")
    op.drop_column("users", "last_login_at")
