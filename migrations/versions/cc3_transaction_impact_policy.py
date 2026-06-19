"""Add transaction impact policy for credit-card launches.

Revision ID: cc3_transaction_impact_policy
Revises: gc1_goal_contrib_date
Create Date: 2026-06-19 01:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "cc3_transaction_impact_policy"
down_revision = "gc1_goal_contrib_date"
branch_labels = None
depends_on = None

_TABLE = "transactions"
_COLUMN = "impact_policy"
_CONSTRAINT = "ck_transactions_impact_policy"
_VALUES = ("full", "cards_only", "planned_until_bill")


def _transaction_columns() -> set[str]:
    inspector = sa.inspect(op.get_context().connection)
    return {col["name"] for col in inspector.get_columns(_TABLE)}


def _transaction_checks() -> set[str]:
    inspector = sa.inspect(op.get_context().connection)
    return {check["name"] for check in inspector.get_check_constraints(_TABLE)}


def upgrade() -> None:
    if _COLUMN not in _transaction_columns():
        op.add_column(
            _TABLE,
            sa.Column(
                _COLUMN,
                sa.String(length=32),
                nullable=False,
                server_default="full",
            ),
        )

    if _CONSTRAINT not in _transaction_checks():
        op.create_check_constraint(
            _CONSTRAINT,
            _TABLE,
            f"{_COLUMN} IN ({', '.join(repr(value) for value in _VALUES)})",
        )


def downgrade() -> None:
    if _CONSTRAINT in _transaction_checks():
        op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    if _COLUMN in _transaction_columns():
        op.drop_column(_TABLE, _COLUMN)
