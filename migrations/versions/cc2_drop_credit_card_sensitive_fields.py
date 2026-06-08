"""cc2 — drop sensitive physical card fields.

Credit cards no longer collect, expose, or persist physical-card digits or
validity dates. The product only needs operational metadata such as bank,
brand, limits, bill cycle and benefits.

Revision ID: cc2_card_privacy
Revises: cc1_credit_card_fk_set_null
Create Date: 2026-06-07

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "cc2_card_privacy"
down_revision = "cc1_credit_card_fk_set_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_context().connection
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("credit_cards") as batch:
            batch.drop_column("last_four_digits")
            batch.drop_column("validity_date")
        return

    op.drop_column("credit_cards", "last_four_digits")
    op.drop_column("credit_cards", "validity_date")


def downgrade() -> None:
    bind = op.get_context().connection
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("credit_cards") as batch:
            batch.add_column(sa.Column("last_four_digits", sa.String(4), nullable=True))
            batch.add_column(sa.Column("validity_date", sa.Date(), nullable=True))
        return

    op.add_column(
        "credit_cards",
        sa.Column("last_four_digits", sa.String(4), nullable=True),
    )
    op.add_column("credit_cards", sa.Column("validity_date", sa.Date(), nullable=True))
