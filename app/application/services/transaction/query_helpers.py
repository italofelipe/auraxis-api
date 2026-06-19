"""Query helpers for the transaction ledger service.

Contains ordering, update-application, serialisation and month-summary
pagination helpers extracted from ``TransactionLedgerService`` to keep each
module under the 600-line ceiling.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from sqlalchemy import case, func

from app.application.services.transaction.validators import _validation_error
from app.models.credit_card import CreditCard
from app.models.transaction import (
    Transaction,
    TransactionCategory,
    TransactionImpactPolicy,
    TransactionStatus,
    TransactionType,
)
from app.services.transaction_analytics_service import TransactionAnalyticsService
from app.services.transaction_serialization import (
    TransactionPayload,
    serialize_transaction_payload,
)

# ---------------------------------------------------------------------------
# Mutable-field registry (shared with ledger service)
# ---------------------------------------------------------------------------

_MUTABLE_TRANSACTION_FIELDS = frozenset(
    {
        "title",
        "description",
        "observation",
        "is_recurring",
        "is_installment",
        "installment_count",
        "amount",
        "currency",
        "status",
        "type",
        "due_date",
        "start_date",
        "end_date",
        "category",
        "tag_id",
        "account_id",
        "credit_card_id",
        "impact_policy",
        "paid_at",
    }
)

# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def _resolve_due_ordering(order_by: str) -> list[Any]:
    today = date.today()
    title_order = func.lower(func.coalesce(Transaction.title, ""))
    card_order = func.lower(func.coalesce(CreditCard.name, ""))
    overdue_bucket = case((Transaction.due_date < today, 0), else_=1)
    upcoming_bucket = case((Transaction.due_date >= today, 0), else_=1)

    if order_by == "overdue_first":
        return [
            overdue_bucket.asc(),
            Transaction.due_date.asc(),
            title_order.asc(),
            card_order.asc(),
            Transaction.created_at.asc(),
        ]
    if order_by == "upcoming_first":
        return [
            upcoming_bucket.asc(),
            Transaction.due_date.asc(),
            title_order.asc(),
            card_order.asc(),
            Transaction.created_at.asc(),
        ]
    if order_by == "date":
        return [
            Transaction.due_date.asc(),
            title_order.asc(),
            card_order.asc(),
            Transaction.created_at.asc(),
        ]
    if order_by == "title":
        return [
            title_order.asc(),
            Transaction.due_date.asc(),
            card_order.asc(),
            Transaction.created_at.asc(),
        ]
    if order_by == "card":
        return [
            card_order.asc(),
            Transaction.due_date.asc(),
            title_order.asc(),
            Transaction.created_at.asc(),
        ]
    raise _validation_error(
        "Parâmetro 'order_by' inválido. "
        "Use overdue_first, upcoming_first, date, title ou card."
    )


# ---------------------------------------------------------------------------
# Update application
# ---------------------------------------------------------------------------


def _apply_transaction_updates(
    transaction: Transaction, updates: dict[str, Any]
) -> None:
    for field, value in updates.items():
        if field not in _MUTABLE_TRANSACTION_FIELDS:
            continue
        if field == "type" and value is not None:
            setattr(transaction, field, TransactionType(str(value).lower()))
            continue
        if field == "status" and value is not None:
            setattr(transaction, field, TransactionStatus(str(value).lower()))
            continue
        if field == "category":
            setattr(
                transaction,
                field,
                TransactionCategory(str(value).lower()) if value else None,
            )
            continue
        if field == "impact_policy" and value is not None:
            setattr(transaction, field, TransactionImpactPolicy(str(value).lower()))
            continue
        setattr(transaction, field, value)


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _serialize_transaction(transaction: Transaction) -> TransactionPayload:
    return serialize_transaction_payload(transaction)


# ---------------------------------------------------------------------------
# Month-summary pagination
# ---------------------------------------------------------------------------


def _resolve_month_summary_page(
    *,
    analytics: TransactionAnalyticsService,
    year: int,
    month_number: int,
    page: int,
    page_size: int,
) -> tuple[int, list[Transaction]]:
    analytics_type = type(analytics)
    supports_paginated_path = (
        getattr(analytics_type, "get_month_transaction_count", None)
        is not TransactionAnalyticsService.get_month_transaction_count
        and getattr(analytics_type, "get_month_transactions_page", None)
        is not TransactionAnalyticsService.get_month_transactions_page
    )
    paginated_count = getattr(analytics, "get_month_transaction_count", None)
    paginated_page = getattr(analytics, "get_month_transactions_page", None)
    if (
        supports_paginated_path
        and callable(paginated_count)
        and callable(paginated_page)
    ):
        total_transactions = int(paginated_count(year=year, month_number=month_number))
        transactions = cast(
            list[Transaction],
            paginated_page(
                year=year,
                month_number=month_number,
                page=page,
                per_page=page_size,
            ),
        )
        return total_transactions, transactions

    transactions = analytics.get_month_transactions(
        year=year, month_number=month_number
    )
    start_index = max(0, (page - 1) * page_size)
    end_index = start_index + page_size
    return len(transactions), transactions[start_index:end_index]
