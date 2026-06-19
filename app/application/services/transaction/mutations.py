"""Mutation / query-building helpers for the transaction ledger service.

Extracted from ``TransactionLedgerService`` to keep the service focused on
orchestration (validate → call helper → persist → respond).

Contents:

- ``assert_owned_references`` — ownership enforcement for tag/account/card refs.
- ``normalize_paid_at_for_update`` — paid_at × status invariant for updates.
- ``build_installment_transactions`` — build the N-row installment batch.
- ``build_transaction_kwargs`` — map a normalised payload → ``Transaction`` ctor args.
- ``apply_active_transaction_filters`` — optional-filter application for list queries.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from dateutil.relativedelta import relativedelta

from app.application.services.transaction.validators import (
    _validation_error,
    coerce_datetime,
    normalize_currency,
    normalize_impact_policy,
    normalize_transaction_status,
    normalize_transaction_type,
)
from app.models.transaction import (
    RecurrenceUnit,
    Transaction,
    TransactionCategory,
    TransactionStatus,
    TransactionType,
)
from app.services.transaction_reference_authorization_service import (
    TransactionReferenceAuthorizationError,
    enforce_transaction_reference_ownership,
)
from app.utils.datetime_utils import utc_now_compatible_with


def assert_owned_references(
    *,
    user_id: UUID,
    tag_id: UUID | None,
    account_id: UUID | None,
    credit_card_id: UUID | None,
) -> None:
    """Raise ``TransactionApplicationError`` if any ref doesn't belong to user."""
    try:
        enforce_transaction_reference_ownership(
            user_id=user_id,
            tag_id=tag_id,
            account_id=account_id,
            credit_card_id=credit_card_id,
        )
    except TransactionReferenceAuthorizationError as exc:
        message = (
            str(exc.args[0]) if exc.args else "Referência inválida para transação."
        )
        raise _validation_error(message) from exc


def normalize_paid_at_for_update(normalized: dict[str, Any]) -> None:
    """Validate and coerce the ``paid_at`` field in-place for an update payload.

    Enforces the invariant: ``paid_at`` is required when marking a transaction
    as PAID, and is forbidden for any other status. Coerces ISO-8601 strings to
    ``datetime`` and rejects future timestamps.
    """
    status = str(normalized.get("status", "")).strip().lower()
    paid_at_value = normalized.get("paid_at")

    if status == "paid" and not paid_at_value:
        raise _validation_error(
            "É obrigatório informar 'paid_at' ao marcar a transação "
            "como paga (status=PAID)."
        )
    if paid_at_value and status != "paid":
        raise _validation_error(
            "'paid_at' só pode ser definido se o status for 'PAID'."
        )
    if "paid_at" not in normalized or paid_at_value is None:
        return

    parsed_paid_at = coerce_datetime(paid_at_value, field_name="paid_at")
    if parsed_paid_at > utc_now_compatible_with(parsed_paid_at):
        raise _validation_error("'paid_at' não pode ser uma data futura.")
    normalized["paid_at"] = parsed_paid_at


def build_transaction_kwargs(
    *,
    user_id: UUID,
    normalized: dict[str, Any],
    tx_type: TransactionType,
    tx_status: TransactionStatus,
    amount: Decimal,
    due_date: date,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any]:
    """Map a pre-normalised payload to ``Transaction`` constructor kwargs."""
    raw_category = normalized.get("category")
    category = TransactionCategory(raw_category) if raw_category else None
    raw_unit = normalized.get("recurrence_unit")
    recurrence_unit = RecurrenceUnit(raw_unit) if raw_unit else RecurrenceUnit.month
    recurrence_interval = int(normalized.get("recurrence_interval") or 1)
    return {
        "user_id": user_id,
        "title": str(normalized.get("title", "")),
        "amount": amount,
        "type": tx_type,
        "due_date": due_date,
        "start_date": start_date,
        "end_date": end_date,
        "description": normalized.get("description"),
        "observation": normalized.get("observation"),
        "is_recurring": bool(normalized.get("is_recurring", False)),
        "is_installment": bool(normalized.get("is_installment", False)),
        "installment_count": normalized.get("installment_count"),
        "recurrence_interval": recurrence_interval,
        "recurrence_unit": recurrence_unit,
        "category": category,
        "tag_id": normalized.get("tag_id"),
        "account_id": normalized.get("account_id"),
        "credit_card_id": normalized.get("credit_card_id"),
        "impact_policy": normalize_impact_policy(normalized.get("impact_policy")),
        "status": tx_status,
        "currency": normalize_currency(normalized.get("currency")),
    }


def build_installment_transactions(
    *,
    user_id: UUID,
    normalized: dict[str, Any],
    tx_type: TransactionType,
    tx_status: TransactionStatus,
    due_date: date,
    start_date: date | None,
    end_date: date | None,
    count: int,
    installment_amounts: list[Any],
) -> list[Transaction]:
    """Build N Transaction rows for an installment batch, sharing a group id."""
    group_id = uuid4()
    title = str(normalized.get("title", "")).strip()
    currency = normalize_currency(normalized.get("currency"))
    raw_category = normalized.get("category")
    category = TransactionCategory(raw_category) if raw_category else None
    impact_policy = normalize_impact_policy(normalized.get("impact_policy"))
    return [
        Transaction(
            user_id=user_id,
            title=f"{title} ({idx + 1}/{count})",
            amount=installment_amounts[idx],
            type=tx_type,
            due_date=due_date + relativedelta(months=idx),
            start_date=start_date,
            end_date=end_date,
            description=normalized.get("description"),
            observation=normalized.get("observation"),
            is_recurring=bool(normalized.get("is_recurring", False)),
            is_installment=True,
            installment_count=count,
            category=category,
            tag_id=normalized.get("tag_id"),
            account_id=normalized.get("account_id"),
            credit_card_id=normalized.get("credit_card_id"),
            impact_policy=impact_policy,
            status=tx_status,
            currency=currency,
            installment_group_id=group_id,
        )
        for idx in range(count)
    ]


def apply_active_transaction_filters(
    query: Any,
    *,
    transaction_type: str | None,
    status: str | None,
    start_date: date | None,
    end_date: date | None,
    tag_id: UUID | None,
    account_id: UUID | None,
    credit_card_id: UUID | None,
) -> Any:
    """Apply optional filters to an active-transactions list query."""
    if transaction_type:
        query = query.filter(
            Transaction.type == normalize_transaction_type(transaction_type)
        )
    if status:
        query = query.filter(Transaction.status == normalize_transaction_status(status))
    if start_date:
        query = query.filter(Transaction.due_date >= start_date)
    if end_date:
        query = query.filter(Transaction.due_date <= end_date)
    if tag_id:
        query = query.filter(Transaction.tag_id == tag_id)
    if account_id:
        query = query.filter(Transaction.account_id == account_id)
    if credit_card_id:
        query = query.filter(Transaction.credit_card_id == credit_card_id)
    return query


def normalize_update_type_and_status(normalized: dict[str, Any]) -> None:
    """Coerce enum-backed strings on an update payload (in-place)."""
    if "type" in normalized and normalized["type"] is not None:
        normalized["type"] = normalize_transaction_type(normalized["type"]).value
    if "status" in normalized and normalized["status"] is not None:
        normalized["status"] = normalize_transaction_status(normalized["status"]).value
    if "impact_policy" in normalized and normalized["impact_policy"] is not None:
        normalized["impact_policy"] = normalize_impact_policy(
            normalized["impact_policy"]
        ).value


__all__ = [
    "apply_active_transaction_filters",
    "assert_owned_references",
    "build_installment_transactions",
    "build_transaction_kwargs",
    "normalize_paid_at_for_update",
    "normalize_update_type_and_status",
]
