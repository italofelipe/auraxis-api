"""add transactions.recurrence_series_id + backfill — #1444

Links all occurrences of one recurring series so the API can delete a single
occurrence or the whole series (DELETE /transactions/{id}?scope=series).

Revision ID: rs1_recurrence_series_id
Revises: sq1_simulation_quota_usage
Create Date: 2026-06-03

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "rs1_recurrence_series_id"
down_revision = "sq1_simulation_quota_usage"
branch_labels = None
depends_on = None

TABLE = "transactions"
COLUMN = "recurrence_series_id"
INDEX = "ix_transactions_user_recurrence_series"


def _has_column(table: str, column: str) -> bool:
    """Return True when *column* already exists on *table*."""
    inspector = sa.inspect(op.get_context().connection)
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(table: str, index: str) -> bool:
    """Return True when *index* already exists on *table*."""
    inspector = sa.inspect(op.get_context().connection)
    return any(idx["name"] == index for idx in inspector.get_indexes(table))


def upgrade() -> None:
    # Idempotent: tolerate prod drift where the column/index already exist.
    if not _has_column(TABLE, COLUMN):
        op.add_column(TABLE, sa.Column(COLUMN, UUID(as_uuid=True), nullable=True))
    if not _has_index(TABLE, INDEX):
        op.create_index(INDEX, TABLE, ["user_id", COLUMN])

    # Backfill: every recurring row's series key is the originating template id,
    # which the recurrence service stores in installment_group_id (falling back
    # to the row's own id for templates without a group).
    op.execute(
        sa.text(
            "UPDATE transactions "
            "SET recurrence_series_id = COALESCE(installment_group_id, id) "
            "WHERE is_recurring AND recurrence_series_id IS NULL"
        )
    )


def downgrade() -> None:
    if _has_index(TABLE, INDEX):
        op.drop_index(INDEX, table_name=TABLE)
    if _has_column(TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
