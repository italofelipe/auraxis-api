"""credit_card_extension

Adds enrichment fields to credit_cards table for the Credit Cards Hub MVP-3:
bank, description, benefits (JSON-encoded list in Text), validity_date,
created_at, updated_at.

All fields are nullable or have server_default so no backfill is required and
the migration is safe to deploy without downtime.

Revision ID: cc1_credit_card_extension
Revises: cons1
Create Date: 2026-05-17 16:00:00.000000

Refs: #1284 (auraxis-api), MVP-3 wiki (auraxis-platform).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "cc1_credit_card_extension"
down_revision = "cons1"
branch_labels = None
depends_on = None


def _credit_cards_columns() -> set[str]:
    """Return existing column names on the ``credit_cards`` table."""
    inspector = sa.inspect(op.get_context().connection)
    return {col["name"] for col in inspector.get_columns("credit_cards")}


def upgrade() -> None:
    # Idempotent: prod carries drift from partial/hotfix runs, so guard each
    # add so a re-run of `flask db upgrade` reconciles instead of failing with
    # "column already exists". All columns are nullable or have a server_default,
    # so adding them on a fresh DB stays downtime-safe.
    existing = _credit_cards_columns()

    if "bank" not in existing:
        op.add_column("credit_cards", sa.Column("bank", sa.String(80), nullable=True))
    if "description" not in existing:
        op.add_column(
            "credit_cards", sa.Column("description", sa.String(300), nullable=True)
        )
    if "benefits" not in existing:
        op.add_column("credit_cards", sa.Column("benefits", sa.Text(), nullable=True))
    if "validity_date" not in existing:
        op.add_column(
            "credit_cards", sa.Column("validity_date", sa.Date(), nullable=True)
        )
    if "created_at" not in existing:
        op.add_column(
            "credit_cards",
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    if "updated_at" not in existing:
        op.add_column(
            "credit_cards",
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    op.drop_column("credit_cards", "updated_at")
    op.drop_column("credit_cards", "created_at")
    op.drop_column("credit_cards", "validity_date")
    op.drop_column("credit_cards", "benefits")
    op.drop_column("credit_cards", "description")
    op.drop_column("credit_cards", "bank")
