from __future__ import annotations

from typing import TypedDict

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
        "start_date": (
            transaction.start_date.isoformat() if transaction.start_date else None
        ),
        "end_date": transaction.end_date.isoformat() if transaction.end_date else None,
        "description": transaction.description,
        "observation": transaction.observation,
        "is_recurring": transaction.is_recurring,
        "is_installment": transaction.is_installment,
        "installment_count": transaction.installment_count,
        "recurrence_interval": getattr(transaction, "recurrence_interval", 1) or 1,
        "recurrence_unit": (
            transaction.recurrence_unit.value
            if getattr(transaction, "recurrence_unit", None)
            else "month"
        ),
        "category": (
            transaction.category.value
            if getattr(transaction, "category", None)
            else None
        ),
        "tag_id": str(transaction.tag_id) if transaction.tag_id else None,
        "account_id": str(transaction.account_id) if transaction.account_id else None,
        "credit_card_id": (
            str(transaction.credit_card_id) if transaction.credit_card_id else None
        ),
        "impact_policy": (
            impact_policy.value
            if hasattr(impact_policy, "value")
            else str(impact_policy or "full")
        ),
        "status": transaction.status.value,
        "currency": transaction.currency,
        "source": transaction.source or "manual",
        "external_id": transaction.external_id,
        "bank_name": transaction.bank_name,
        "installment_group_id": (
            str(installment_group_id) if installment_group_id is not None else None
        ),
        "paid_at": paid_at.isoformat() if paid_at is not None else None,
        "created_at": (
            transaction.created_at.isoformat() if transaction.created_at else None
        ),
        "updated_at": (
            transaction.updated_at.isoformat() if transaction.updated_at else None
        ),
    }


__all__ = ["TransactionPayload", "serialize_transaction_payload"]
