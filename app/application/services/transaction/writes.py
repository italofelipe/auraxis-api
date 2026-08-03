"""Write-side orchestration for the transaction ledger service.

Contains the full ``create`` and ``update`` flows (validation, normalisation,
persistence, cache invalidation) as free functions so the service class stays
focused on composition.
"""

from __future__ import annotations

import logging
from typing import Any, Callable
from uuid import UUID

from app.application.services.transaction.errors import TransactionApplicationError
from app.application.services.transaction.mutations import (
    assert_owned_references,
    build_installment_transactions,
    build_transaction_kwargs,
    normalize_paid_at_for_create,
    normalize_paid_at_for_update,
    normalize_update_type_and_status,
)
from app.application.services.transaction.query_helpers import (
    _apply_transaction_updates,
    _serialize_transaction,
)
from app.application.services.transaction.validators import (
    _normalize_installment_count,
    _validate_recurring_payload,
    _validation_error,
    coerce_date,
    normalize_decimal_amount,
    normalize_transaction_status,
    normalize_transaction_type,
)
from app.extensions.database import db
from app.models.transaction import Transaction
from app.services.recurrence_service import RecurrenceService
from app.services.transaction_serialization import TransactionPayload

logger = logging.getLogger(__name__)


def execute_create_transaction(
    *,
    user_id: UUID,
    payload: dict[str, Any],
    installment_amount_builder: Callable[[Any, int], list[Any]],
    invalidate_cache: Callable[[], None],
) -> dict[str, Any]:
    normalized = dict(payload)
    tx_type = normalize_transaction_type(normalized.get("type"))
    tx_status = normalize_transaction_status(normalized.get("status"))
    amount = normalize_decimal_amount(normalized.get("amount"))
    normalize_paid_at_for_create(normalized, tx_status=tx_status)
    due_date = coerce_date(
        normalized.get("due_date"), field_name="due_date", required=True
    )
    if due_date is None:
        raise _validation_error(
            "Parâmetro 'due_date' é obrigatório no formato YYYY-MM-DD."
        )
    start_date = coerce_date(
        normalized.get("start_date"), field_name="start_date", required=False
    )
    end_date = coerce_date(
        normalized.get("end_date"), field_name="end_date", required=False
    )

    recurring_error = _validate_recurring_payload(
        is_recurring=bool(normalized.get("is_recurring", False)),
        due_date=due_date,
        start_date=start_date,
        end_date=end_date,
    )
    if recurring_error:
        raise _validation_error(recurring_error)

    assert_owned_references(
        user_id=user_id,
        tag_id=normalized.get("tag_id"),
        account_id=normalized.get("account_id"),
        credit_card_id=normalized.get("credit_card_id"),
    )

    if normalized.get("is_installment") and normalized.get("installment_count"):
        count = _normalize_installment_count(normalized.get("installment_count"))
        installment_amounts = installment_amount_builder(amount, count)
        transactions = build_installment_transactions(
            user_id=user_id,
            normalized=normalized,
            tx_type=tx_type,
            tx_status=tx_status,
            due_date=due_date,
            start_date=start_date,
            end_date=end_date,
            count=count,
            installment_amounts=installment_amounts,
        )
        try:
            db.session.add_all(transactions)
            db.session.commit()
        except TransactionApplicationError:
            raise
        except Exception:
            db.session.rollback()
            raise

        return {
            "message": "Transações parceladas criadas com sucesso",
            "items": [_serialize_transaction(item) for item in transactions],
            "legacy_key": "transactions",
        }

    transaction = Transaction(
        **build_transaction_kwargs(
            user_id=user_id,
            normalized=normalized,
            tx_type=tx_type,
            tx_status=tx_status,
            amount=amount,
            due_date=due_date,
            start_date=start_date,
            end_date=end_date,
        )
    )
    try:
        db.session.add(transaction)
        db.session.commit()
        invalidate_cache()
    except TransactionApplicationError:
        raise
    except Exception:
        db.session.rollback()
        raise

    # Populate future occurrences immediately so a recurring transaction shows
    # up in upcoming months without waiting for the daily reconciliation cron.
    # Best-effort: a failure here must not fail the create that already
    # committed — the cron will reconcile.
    if transaction.is_recurring:
        try:
            RecurrenceService.materialize_for_template(transaction)
            invalidate_cache()
        except Exception:
            db.session.rollback()
            logger.warning(
                "recurrence: inline materialisation failed for transaction %s; "
                "cron will reconcile",
                transaction.id,
                exc_info=True,
            )

    return {
        "message": "Transação criada com sucesso",
        "items": [_serialize_transaction(transaction)],
        "legacy_key": "transaction",
    }


def execute_update_transaction(
    *,
    user_id: UUID,
    transaction: Transaction,
    payload: dict[str, Any],
    invalidate_cache: Callable[[], None],
) -> TransactionPayload:
    normalized = dict(payload)
    normalize_update_type_and_status(normalized)
    normalize_paid_at_for_update(normalized)

    due_date = coerce_date(
        normalized.get("due_date", transaction.due_date),
        field_name="due_date",
        required=True,
    )
    start_date = coerce_date(
        normalized["start_date"]
        if "start_date" in normalized
        else transaction.start_date,
        field_name="start_date",
        required=False,
    )
    end_date = coerce_date(
        normalized["end_date"] if "end_date" in normalized else transaction.end_date,
        field_name="end_date",
        required=False,
    )
    effective_is_recurring = bool(
        normalized["is_recurring"]
        if "is_recurring" in normalized
        else transaction.is_recurring
    )
    recurring_error = _validate_recurring_payload(
        is_recurring=effective_is_recurring,
        due_date=due_date,
        start_date=start_date,
        end_date=end_date,
    )
    if recurring_error:
        raise _validation_error(recurring_error)

    assert_owned_references(
        user_id=user_id,
        tag_id=normalized.get("tag_id", transaction.tag_id),
        account_id=normalized.get("account_id", transaction.account_id),
        credit_card_id=normalized.get("credit_card_id", transaction.credit_card_id),
    )

    try:
        _apply_transaction_updates(transaction, normalized)
        db.session.commit()
        invalidate_cache()
    except Exception:
        db.session.rollback()
        raise

    return _serialize_transaction(transaction)


__all__ = [
    "execute_create_transaction",
    "execute_update_transaction",
]
