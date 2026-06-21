"""List-query helpers for the transaction ledger service.

Implements the read-side list paths (``active`` and ``due``) as free
functions so ``TransactionLedgerService`` stays focused on orchestration
and fits under the per-module LOC ceiling.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from app.application.services.transaction.mutations import (
    apply_active_transaction_filters,
)
from app.application.services.transaction.query_helpers import (
    _resolve_due_ordering,
    _serialize_transaction,
)
from app.application.services.transaction.validators import (
    _START_END_DATE_ORDER_MESSAGE,
    _START_END_DATE_REQUIRED_MESSAGE,
    _validation_error,
    coerce_date,
)
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction, TransactionType


def fetch_active_transactions(
    *,
    user_id: UUID,
    page: int,
    per_page: int,
    transaction_type: str | None,
    status: str | None,
    start_date: date | None,
    end_date: date | None,
    tag_id: UUID | None,
    account_id: UUID | None,
    credit_card_id: UUID | None,
) -> dict[str, Any]:
    query = Transaction.query.filter_by(user_id=user_id, deleted=False)
    query = apply_active_transaction_filters(
        query,
        user_id=user_id,
        transaction_type=transaction_type,
        status=status,
        start_date=start_date,
        end_date=end_date,
        tag_id=tag_id,
        account_id=account_id,
        credit_card_id=credit_card_id,
    )

    total = query.count()
    pages = (total + per_page - 1) // per_page if total else 0
    transactions = (
        query.order_by(Transaction.due_date.desc(), Transaction.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "items": [_serialize_transaction(item) for item in transactions],
        "pagination": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        },
    }


def fetch_due_transactions(
    *,
    user_id: UUID,
    start_date: str | date | None,
    end_date: str | date | None,
    page: int,
    per_page: int,
    order_by: str = "overdue_first",
) -> dict[str, Any]:
    parsed_start_date = coerce_date(start_date, field_name="start_date", required=False)
    parsed_end_date = coerce_date(end_date, field_name="end_date", required=False)
    if not parsed_start_date and not parsed_end_date:
        raise _validation_error(_START_END_DATE_REQUIRED_MESSAGE)
    if parsed_start_date and parsed_end_date and parsed_start_date > parsed_end_date:
        raise _validation_error(_START_END_DATE_ORDER_MESSAGE)

    order_clauses = _resolve_due_ordering(
        str(order_by or "overdue_first").strip().lower()
    )

    base_query = Transaction.query.filter_by(user_id=user_id, deleted=False)
    if parsed_start_date:
        base_query = base_query.filter(Transaction.due_date >= parsed_start_date)
    if parsed_end_date:
        base_query = base_query.filter(Transaction.due_date <= parsed_end_date)

    total_transactions = base_query.count()
    income_transactions = base_query.filter(
        Transaction.type == TransactionType.INCOME
    ).count()
    expense_transactions = base_query.filter(
        Transaction.type == TransactionType.EXPENSE
    ).count()
    pages = (total_transactions + per_page - 1) // per_page if total_transactions else 0

    transactions = (
        base_query.outerjoin(CreditCard, Transaction.credit_card_id == CreditCard.id)
        .order_by(*order_clauses)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    return {
        "items": [_serialize_transaction(item) for item in transactions],
        "counts": {
            "total_transactions": total_transactions,
            "income_transactions": income_transactions,
            "expense_transactions": expense_transactions,
        },
        "pagination": {
            "total": total_transactions,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        },
    }


__all__ = [
    "fetch_active_transactions",
    "fetch_due_transactions",
]
