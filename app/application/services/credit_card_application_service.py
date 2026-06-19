"""Credit card application service (#1459).

Deleting a credit card must also remove the debts/expenses charged to it —
otherwise the installments stay visible in the transactions list pointing at a
card that no longer exists. This service deletes a card and soft-deletes every
transaction linked to it (all installments share the same ``credit_card_id``),
in a single transaction.
"""

from __future__ import annotations

from uuid import UUID

from app.extensions.database import db
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction
from app.utils.datetime_utils import utc_now_naive


def delete_card_with_transactions(*, card_id: UUID, user_id: UUID) -> bool:
    """Delete a user's credit card and soft-delete its linked transactions.

    All transactions charged to the card (every installment, since each row
    carries the same ``credit_card_id``) are soft-deleted so they disappear from
    the transactions list, and their ``credit_card_id`` is cleared so the card
    hard-delete cannot trip the foreign key regardless of its ``ondelete`` rule.

    Args:
        card_id: The credit card to delete.
        user_id: The owner; scopes both the card and the transactions.

    Returns:
        True when the card existed and was deleted; False when not found
        (caller maps this to a 404).
    """
    card: CreditCard | None = CreditCard.query.filter_by(
        id=card_id, user_id=user_id
    ).first()
    if card is None:
        return False

    Transaction.query.filter_by(credit_card_id=card_id, user_id=user_id).update(
        {
            "deleted": True,
            "credit_card_id": None,
            "updated_at": utc_now_naive(),
        },
        synchronize_session=False,
    )
    db.session.delete(card)
    db.session.commit()
    return True


__all__ = ["delete_card_with_transactions"]
