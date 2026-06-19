from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import UUID

from flask import Response, current_app

from app.application.errors import PublicValidationError
from app.auth import AuthContextError, current_token_jti, get_active_auth_context
from app.controllers.response_contract import (
    CONTRACT_HEADER,
    CONTRACT_V2,
    compat_error_response,
    compat_success_response,
    is_v2_contract,
)
from app.extensions.jwt_callbacks import is_token_revoked
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.services.transaction_reference_authorization_service import (
    TransactionReferenceAuthorizationError,
    enforce_transaction_reference_ownership,
)
from app.services.transaction_serialization import (
    TransactionPayload,
    serialize_transaction_payload,
)
from app.utils.response_builder import json_response

INVALID_TOKEN_MESSAGE = "Token inválido."
DEFAULT_DEPRECATION_SUNSET = "Tue, 30 Jun 2026 23:59:59 GMT"
MUTABLE_TRANSACTION_FIELDS = frozenset(
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
        "tag_id",
        "account_id",
        "credit_card_id",
        "impact_policy",
        "paid_at",
    }
)


def _is_v2_contract() -> bool:
    return is_v2_contract()


def _json_response(payload: dict[str, Any], status_code: int) -> Response:
    return json_response(payload, status_code=status_code)


def _compat_success(
    *,
    legacy_payload: dict[str, Any],
    status_code: int,
    message: str,
    data: dict[str, Any],
    meta: dict[str, Any] | None = None,
) -> Response:
    return compat_success_response(
        legacy_payload=legacy_payload,
        status_code=status_code,
        message=message,
        data=data,
        meta=meta,
    )


def _compat_error(
    *,
    legacy_payload: dict[str, Any],
    status_code: int,
    message: str,
    error_code: str,
    details: dict[str, Any] | None = None,
) -> Response:
    return compat_error_response(
        legacy_payload=legacy_payload,
        status_code=status_code,
        message=message,
        error_code=error_code,
        details=details,
    )


def _parse_positive_int(value: str | None, *, default: int, field_name: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise PublicValidationError(
            f"Parâmetro '{field_name}' inválido. Informe um inteiro positivo."
        ) from exc
    if parsed < 1:
        raise PublicValidationError(
            f"Parâmetro '{field_name}' inválido. Informe um inteiro positivo."
        )
    return parsed


def _parse_optional_uuid(value: str | None, field_name: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise PublicValidationError(
            f"Parâmetro '{field_name}' inválido. Informe um UUID válido."
        ) from exc


def _parse_optional_date(value: str | None, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise PublicValidationError(
            f"Parâmetro '{field_name}' inválido. Use o formato YYYY-MM-DD."
        ) from exc


def _parse_month_param(value: str | None) -> tuple[int, int, str]:
    if not value:
        raise PublicValidationError(
            "Parâmetro 'month' é obrigatório no formato YYYY-MM."
        )
    try:
        year, month_number = map(int, value.split("-"))
    except ValueError as exc:
        raise PublicValidationError("Formato de mês inválido. Use YYYY-MM.") from exc

    if month_number < 1 or month_number > 12:
        raise PublicValidationError("Formato de mês inválido. Use YYYY-MM.")

    return year, month_number, f"{year:04d}-{month_number:02d}"


def _validate_recurring_payload(
    *,
    is_recurring: bool,
    due_date: date | None,
    start_date: date | None,
    end_date: date | None,
) -> str | None:
    if not is_recurring:
        if start_date and end_date and start_date > end_date:
            return "Parâmetro 'start_date' não pode ser maior que 'end_date'."
        return None

    if not start_date or not end_date:
        return (
            "Transações recorrentes exigem 'start_date' e 'end_date' "
            "no formato YYYY-MM-DD."
        )

    if start_date > end_date:
        return "Parâmetro 'start_date' não pode ser maior que 'end_date'."

    if due_date is None:
        return "Transações recorrentes exigem 'due_date' no formato YYYY-MM-DD."

    if due_date < start_date or due_date > end_date:
        return "Parâmetro 'due_date' deve estar entre 'start_date' e 'end_date'."

    return None


def _guard_revoked_token() -> Response | None:
    """
    Reject requests made with revoked JWTs.

    Notes
    - We keep this in `transaction.utils` to avoid duplicate implementations
      across multiple transaction resources.
    - This intentionally validates the active auth context here because
      resources may call it before reading identity claims.
    """

    try:
        context = get_active_auth_context()
    except AuthContextError:
        return _invalid_token_response()
    jti = context.jti if context is not None else current_token_jti(optional=True)
    if jti is not None and is_token_revoked(jti):
        return _invalid_token_response()
    return None


def _resolve_transaction_ordering(order_by: str, order: str) -> Any:
    allowed_order_by: dict[str, Any] = {
        "due_date": Transaction.due_date,
        "created_at": Transaction.created_at,
        "amount": Transaction.amount,
        "title": Transaction.title,
    }
    if order_by not in allowed_order_by:
        raise PublicValidationError(
            "Parâmetro 'order_by' inválido. Use due_date, created_at, amount ou title."
        )
    if order not in {"asc", "desc"}:
        raise PublicValidationError("Parâmetro 'order' inválido. Use asc ou desc.")

    column = allowed_order_by[order_by]
    return column.asc() if order == "asc" else column.desc()


def _build_installment_amounts(total: Decimal, count: int) -> list[Decimal]:
    if count < 1:
        raise PublicValidationError("'installment_count' deve ser maior que zero.")

    normalized_total = total.quantize(Decimal("0.01"))
    base_amount = (normalized_total / count).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )
    amounts = [base_amount] * count

    distributed = base_amount * count
    remainder = (normalized_total - distributed).quantize(Decimal("0.01"))
    amounts[-1] = (amounts[-1] + remainder).quantize(Decimal("0.01"))
    return amounts


def _invalid_token_response() -> Response:
    return _compat_error(
        legacy_payload={"error": INVALID_TOKEN_MESSAGE},
        status_code=401,
        message=INVALID_TOKEN_MESSAGE,
        error_code="UNAUTHORIZED",
    )


def _internal_error_response(*, message: str, log_context: str) -> Response:
    current_app.logger.exception(log_context)
    return _compat_error(
        legacy_payload={"error": message},
        status_code=500,
        message=message,
        error_code="INTERNAL_ERROR",
    )


def _apply_deprecation_headers(
    response: Response,
    *,
    successor_endpoint: str,
    successor_method: str,
    sunset: str = DEFAULT_DEPRECATION_SUNSET,
) -> Response:
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = sunset
    response.headers["X-Auraxis-Successor-Endpoint"] = successor_endpoint
    response.headers["X-Auraxis-Successor-Method"] = successor_method
    return response


def _enforce_transaction_reference_ownership_or_error(
    *,
    user_id: UUID,
    tag_id: UUID | None,
    account_id: UUID | None,
    credit_card_id: UUID | None,
) -> str | None:
    try:
        enforce_transaction_reference_ownership(
            user_id=user_id,
            tag_id=tag_id,
            account_id=account_id,
            credit_card_id=credit_card_id,
        )
    except TransactionReferenceAuthorizationError as exc:
        if exc.args:
            return str(exc.args[0])
        return "Referência inválida."
    return None


def _apply_transaction_updates(
    transaction: Transaction, updates: dict[str, Any]
) -> None:
    for field, value in updates.items():
        if field not in MUTABLE_TRANSACTION_FIELDS:
            continue
        if field == "type" and value is not None:
            setattr(transaction, field, TransactionType(str(value).lower()))
            continue
        if field == "status" and value is not None:
            setattr(transaction, field, TransactionStatus(str(value).lower()))
            continue
        setattr(transaction, field, value)


def serialize_transaction(transaction: Transaction) -> TransactionPayload:
    return serialize_transaction_payload(transaction)


__all__ = [
    "INVALID_TOKEN_MESSAGE",
    "CONTRACT_HEADER",
    "CONTRACT_V2",
    "MUTABLE_TRANSACTION_FIELDS",
    "_is_v2_contract",
    "_json_response",
    "_compat_success",
    "_compat_error",
    "_parse_positive_int",
    "_parse_optional_uuid",
    "_parse_optional_date",
    "_parse_month_param",
    "_validate_recurring_payload",
    "_resolve_transaction_ordering",
    "_build_installment_amounts",
    "_invalid_token_response",
    "_internal_error_response",
    "_enforce_transaction_reference_ownership_or_error",
    "_apply_transaction_updates",
    "serialize_transaction",
    "enforce_transaction_reference_ownership",
    "TransactionReferenceAuthorizationError",
]
