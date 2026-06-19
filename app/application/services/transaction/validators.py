"""Domain validators and normalisation helpers for transaction payloads.

These are module-level functions extracted from ``TransactionLedgerService``
to keep each module under the 600-line ceiling.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.application.services.transaction.errors import TransactionApplicationError
from app.models.transaction import (
    TransactionImpactPolicy,
    TransactionStatus,
    TransactionType,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_START_END_DATE_REQUIRED_MESSAGE = (
    "Informe ao menos um parâmetro: 'start_date' ou 'end_date'."
)
_START_END_DATE_ORDER_MESSAGE = (
    "Parâmetro 'start_date' não pode ser maior que 'end_date'."
)

# ---------------------------------------------------------------------------
# Core error factory
# ---------------------------------------------------------------------------


def _validation_error(message: str) -> TransactionApplicationError:
    return TransactionApplicationError(
        message=message,
        code="VALIDATION_ERROR",
        status_code=400,
    )


# ---------------------------------------------------------------------------
# Payload validators
# ---------------------------------------------------------------------------


def _validate_recurring_payload(
    *,
    is_recurring: bool,
    due_date: date | None,
    start_date: date | None,
    end_date: date | None,
) -> str | None:
    if not is_recurring:
        if start_date and end_date and start_date > end_date:
            return _START_END_DATE_ORDER_MESSAGE
        return None

    if not start_date or not end_date:
        return (
            "Transações recorrentes exigem 'start_date' e 'end_date' "
            "no formato YYYY-MM-DD."
        )

    if start_date > end_date:
        return _START_END_DATE_ORDER_MESSAGE

    if due_date is None:
        return "Transações recorrentes exigem 'due_date' no formato YYYY-MM-DD."

    if due_date < start_date or due_date > end_date:
        return "Parâmetro 'due_date' deve estar entre 'start_date' e 'end_date'."

    return None


def _normalize_installment_count(raw_count: Any) -> int:
    try:
        count = int(raw_count)
    except (TypeError, ValueError) as exc:
        raise _validation_error("'installment_count' deve ser maior que zero.") from exc
    if count < 1:
        raise _validation_error("'installment_count' deve ser maior que zero.")
    return count


def _parse_month(value: str) -> tuple[int, int, str]:
    if not value:
        raise _validation_error("Parâmetro 'month' é obrigatório no formato YYYY-MM.")
    try:
        year, month_number = map(int, value.split("-"))
    except ValueError as exc:
        raise _validation_error("Formato de mês inválido. Use YYYY-MM.") from exc

    if month_number < 1 or month_number > 12:
        raise _validation_error("Formato de mês inválido. Use YYYY-MM.")

    return year, month_number, f"{year:04d}-{month_number:02d}"


# ---------------------------------------------------------------------------
# Type / field normalisation helpers
# ---------------------------------------------------------------------------


def normalize_transaction_type(raw_value: Any) -> TransactionType:
    value = str(raw_value or "").strip().lower()
    try:
        return TransactionType(value)
    except ValueError as exc:
        raise _validation_error(
            "Parâmetro 'type' inválido. Use 'income' ou 'expense'."
        ) from exc


def normalize_transaction_status(raw_value: Any) -> TransactionStatus:
    value = str(raw_value or "pending").strip().lower()
    try:
        return TransactionStatus(value)
    except ValueError as exc:
        raise _validation_error(
            "Parâmetro 'status' inválido. "
            "Use paid, pending, cancelled, postponed ou overdue."
        ) from exc


def normalize_impact_policy(raw_value: Any) -> TransactionImpactPolicy:
    value = str(raw_value or TransactionImpactPolicy.FULL.value).strip().lower()
    try:
        return TransactionImpactPolicy(value)
    except ValueError as exc:
        raise _validation_error(
            "Parâmetro 'impact_policy' inválido. "
            "Use full, cards_only ou planned_until_bill."
        ) from exc


def normalize_currency(raw_value: Any) -> str:
    value = str(raw_value or "BRL").strip().upper()
    if not value:
        return "BRL"
    return value


def normalize_decimal_amount(raw_value: Any) -> Decimal:
    try:
        return Decimal(str(raw_value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise _validation_error(
            "Parâmetro 'amount' inválido. Informe um valor numérico válido."
        ) from exc


def coerce_date(
    raw_value: Any,
    *,
    field_name: str,
    required: bool,
) -> date | None:
    if raw_value in (None, ""):
        if required:
            raise _validation_error(
                f"Parâmetro '{field_name}' é obrigatório no formato YYYY-MM-DD."
            )
        return None
    if isinstance(raw_value, date):
        return raw_value
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, str):
        try:
            return datetime.strptime(raw_value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise _validation_error(
                f"Parâmetro '{field_name}' inválido. Use o formato YYYY-MM-DD."
            ) from exc
    raise _validation_error(
        f"Parâmetro '{field_name}' inválido. Use o formato YYYY-MM-DD."
    )


def coerce_datetime(raw_value: Any, *, field_name: str) -> datetime:
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise _validation_error(
                f"Parâmetro '{field_name}' inválido. Use formato datetime ISO-8601."
            ) from exc
    raise _validation_error(
        f"Parâmetro '{field_name}' inválido. Use formato datetime ISO-8601."
    )
