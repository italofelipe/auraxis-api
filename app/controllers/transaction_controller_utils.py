"""Transaction controller utilities compatibility facade."""

from __future__ import annotations

from app.controllers.transaction.utils import (
    CONTRACT_HEADER,
    CONTRACT_V2,
    INVALID_TOKEN_MESSAGE,
    TransactionReferenceAuthorizationError,
    _build_installment_amounts,
    _compat_error,
    _compat_success,
    _enforce_transaction_reference_ownership_or_error,
    _internal_error_response,
    _invalid_token_response,
    _is_v2_contract,
    _json_response,
    _parse_month_param,
    _parse_optional_date,
    _parse_optional_uuid,
    _parse_positive_int,
    _resolve_transaction_ordering,
    _validate_recurring_payload,
    enforce_transaction_reference_ownership,
    serialize_transaction,
)

__all__ = [
    "INVALID_TOKEN_MESSAGE",
    "CONTRACT_HEADER",
    "CONTRACT_V2",
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
    "serialize_transaction",
    "enforce_transaction_reference_ownership",
    "TransactionReferenceAuthorizationError",
]
