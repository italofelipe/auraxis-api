"""Add columns for investor profile suggestion

Revision ID: 20240614
Revises: e3b1f6a2d8c9
Create Date: 2024-06-14 12:00:00

"""

import sqlalchemy as sa
from alembic import op

revision = "20240614"
down_revision = "e3b1f6a2d8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("investor_profile_suggested", sa.String(length=32), nullable=True),
    )
    op.add_column("users", sa.Column("profile_quiz_score", sa.Integer(), nullable=True))
    op.add_column(
        "users", sa.Column("taxonomy_version", sa.String(length=16), nullable=True)
    )


def downgrade():
    op.drop_column("users", "taxonomy_version")
    op.drop_column("users", "profile_quiz_score")
    op.drop_column("users", "investor_profile_suggested")
