"""add transactions.auto_settle — #1516

Opt-in flag for the auto-settle job (F4): when true, the daily
``flask transactions auto-settle`` job marks the transaction as paid once it
comes due. Default false so the ledger is never mutated for transactions the
user did not opt in.

Revision ID: as1_transaction_auto_settle
Revises: cc3_transaction_impact_policy
Create Date: 2026-06-29

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "as1_transaction_auto_settle"
down_revision = "cc3_transaction_impact_policy"
branch_labels = None
depends_on = None

TABLE = "transactions"
COLUMN = "auto_settle"


def _has_column(table: str, column: str) -> bool:
    """Return True when *column* already exists on *table*."""
    inspector = sa.inspect(op.get_context().connection)
    return any(col["name"] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    # Idempotent: tolerate prod drift where the column already exists.
    if not _has_column(TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
