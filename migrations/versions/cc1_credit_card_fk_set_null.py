"""cc1 — transactions.credit_card_id FK ondelete=SET NULL (#1459).

Deleting a credit card must not be blocked by — nor orphan — the transactions
charged to it. The application service soft-deletes and unlinks those rows
explicitly, but the FK is hardened to SET NULL as a data-integrity backstop for
any path that deletes a card directly (raw SQL, future cascades).

The FK was created unnamed in the initial schema, so PostgreSQL auto-named it
``transactions_credit_card_id_fkey``. On SQLite (test runtime the schema comes
from ``db.create_all`` and FKs are not enforced) this migration is a no-op.

Revision ID: cc1_credit_card_fk_set_null
Revises: ai7
Create Date: 2026-06-07

"""

from __future__ import annotations

from alembic import op

revision = "cc1_credit_card_fk_set_null"
down_revision = "ai7"
branch_labels = None
depends_on = None

_FK = "transactions_credit_card_id_fkey"


def upgrade() -> None:
    bind = op.get_context().connection
    if bind.dialect.name == "sqlite":
        return
    op.drop_constraint(_FK, "transactions", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "transactions",
        "credit_cards",
        ["credit_card_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_context().connection
    if bind.dialect.name == "sqlite":
        return
    op.drop_constraint(_FK, "transactions", type_="foreignkey")
    op.create_foreign_key(
        _FK,
        "transactions",
        "credit_cards",
        ["credit_card_id"],
        ["id"],
    )
