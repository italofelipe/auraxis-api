from __future__ import annotations

from typing import Any, TypedDict

from app.models.transaction import Transaction


class TransactionPayload(TypedDict):
    id: str
    title: str
    amount: str
    type: str
    due_date: str
    start_date: str | None
    end_date: str | None
    description: str | None
    observation: str | None
    is_recurring: bool
    is_installment: bool
    installment_count: int | None
    recurrence_interval: int
    recurrence_unit: str
    category: str | None
    tag_id: str | None
    account_id: str | None
    credit_card_id: str | None
    impact_policy: str
    status: str
    currency: str
    source: str
    external_id: str | None
    bank_name: str | None
    installment_group_id: str | None
    paid_at: str | None
    created_at: str | None
    updated_at: str | None


def _isoformat_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _enum_value_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _enum_value_or_default(value: Any, default: str) -> str:
    return _enum_value_or_none(value) or default


def serialize_transaction_payload(transaction: Transaction) -> TransactionPayload:
    installment_group_id = getattr(transaction, "installment_group_id", None)
    paid_at = getattr(transaction, "paid_at", None)
    impact_policy = getattr(transaction, "impact_policy", None)

    return {
        "id": str(transaction.id),
        "title": transaction.title,
        "amount": str(transaction.amount),
        "type": transaction.type.value,
        "due_date": transaction.due_date.isoformat(),
        "start_date": _isoformat_or_none(transaction.start_date),
        "end_date": _isoformat_or_none(transaction.end_date),
        "description": transaction.description,
        "observation": transaction.observation,
        "is_recurring": transaction.is_recurring,
        "is_installment": transaction.is_installment,
        "installment_count": transaction.installment_count,
        "recurrence_interval": getattr(transaction, "recurrence_interval", 1) or 1,
        "recurrence_unit": _enum_value_or_default(
            getattr(transaction, "recurrence_unit", None), "month"
        ),
        "category": _enum_value_or_none(getattr(transaction, "category", None)),
        "tag_id": _str_or_none(transaction.tag_id),
        "account_id": _str_or_none(transaction.account_id),
        "credit_card_id": _str_or_none(transaction.credit_card_id),
        "impact_policy": _enum_value_or_default(impact_policy, "full"),
        "status": transaction.status.value,
        "currency": transaction.currency,
        "source": transaction.source or "manual",
        "external_id": transaction.external_id,
        "bank_name": transaction.bank_name,
        "installment_group_id": _str_or_none(installment_group_id),
        "paid_at": _isoformat_or_none(paid_at),
        "created_at": _isoformat_or_none(transaction.created_at),
        "updated_at": _isoformat_or_none(transaction.updated_at),
    }


__all__ = ["TransactionPayload", "serialize_transaction_payload"]
