"""Auto-settle service for opt-in transactions (F4, #1516).

Marks transactions the user opted into (``auto_settle=True``) as paid once they
come due. Runs from the daily ``flask transactions auto-settle`` job. Safe by
design: only touches open (pending/postponed) opted-in rows whose ``due_date``
has arrived — never future occurrences and never rows the user did not opt in.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.extensions.database import db
from app.models.transaction import Transaction, TransactionStatus
from app.utils.datetime_utils import utc_now_naive

# Only open statuses are auto-settled; paid/cancelled/overdue are left untouched.
_SETTLEABLE_STATUSES = (TransactionStatus.PENDING, TransactionStatus.POSTPONED)


class TransactionAutoSettleService:
    """Settles due, opted-in transactions in a single batch."""

    @staticmethod
    def _due_query(reference_date: date) -> Any:
        """Builds the query for due, opted-in, open transactions."""
        return Transaction.query.filter(
            Transaction.auto_settle.is_(True),
            Transaction.deleted.is_(False),
            Transaction.due_date <= reference_date,
            Transaction.status.in_(_SETTLEABLE_STATUSES),
        )

    @classmethod
    def count_due(cls, reference_date: date | None = None) -> int:
        """Counts how many transactions would be auto-settled (dry-run)."""
        today = reference_date or date.today()
        return int(cls._due_query(today).count())

    @classmethod
    def settle_due(cls, reference_date: date | None = None) -> int:
        """Marks due, opted-in, open transactions as paid.

        Idempotent: a second run finds nothing because settled rows are no longer
        in an open status.

        :param reference_date: "today" override (defaults to ``date.today()``).
        :returns: number of transactions settled.
        """
        today = reference_date or date.today()
        settled_at = utc_now_naive()
        settled = 0
        for transaction in cls._due_query(today).all():
            transaction.status = TransactionStatus.PAID
            transaction.paid_at = settled_at
            settled += 1
        if settled:
            db.session.commit()
        return settled


__all__ = ["TransactionAutoSettleService"]
