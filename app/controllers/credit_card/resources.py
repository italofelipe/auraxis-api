"""CreditCard controller resources — CRUD endpoints for user credit cards."""

from __future__ import annotations

# mypy: disable-error-code=untyped-decorator
from typing import Any
from uuid import UUID

from flask import request

from app.application.services.credit_card_application_service import (
    delete_card_with_transactions,
)
from app.auth import current_user_id
from app.controllers.response_contract import compat_error_tuple, compat_success_tuple
from app.decorators import require_email_verified
from app.extensions.database import db
from app.models.credit_card import CreditCard
from app.utils.typed_decorators import typed_jwt_required as jwt_required

from .blueprint import credit_card_bp

MISSING_NAME_MESSAGE = "Field 'name' is required"
NAME_TOO_LONG_MESSAGE = "Field 'name' must be at most 100 characters"
CREDIT_CARD_NOT_FOUND_MESSAGE = "Credit card not found"
CREDIT_CARD_BRAND_VALUES = ("visa", "mastercard", "elo", "hipercard", "amex", "other")
INVALID_BRAND_MESSAGE = (
    "Field 'brand' must be one of: visa, mastercard, elo, hipercard, amex, other"
)
INVALID_DAY_MESSAGE = (
    "Fields 'closing_day' and 'due_day' must be integers between 1 and 28"
)
INVALID_BENEFITS_MESSAGE = (
    "Field 'benefits' must be a list of strings (max 12 items × 120 chars each)"
)
BANK_TOO_LONG_MESSAGE = "Field 'bank' must be at most 80 characters"
DESCRIPTION_TOO_LONG_MESSAGE = "Field 'description' must be at most 300 characters"

BENEFITS_MAX_ITEMS = 12
BENEFITS_MAX_ITEM_LENGTH = 120
BANK_MAX_LENGTH = 80
DESCRIPTION_MAX_LENGTH = 300


def _serialize_card(c: CreditCard) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "name": c.name,
        "brand": c.brand,
        "limit_amount": float(c.limit_amount) if c.limit_amount is not None else None,
        "closing_day": c.closing_day,
        "due_day": c.due_day,
        "bank": c.bank,
        "description": c.description,
        "benefits": c.benefits_list,
        "created_at": c.created_at.isoformat() if c.created_at is not None else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at is not None else None,
    }


@credit_card_bp.route("", methods=["GET"])
@jwt_required()
def list_credit_cards() -> tuple[dict[str, Any], int]:
    """List all credit cards belonging to the authenticated user."""
    user_id = current_user_id()
    cards = CreditCard.query.filter_by(user_id=user_id).order_by(CreditCard.name).all()
    data = {
        "credit_cards": [_serialize_card(c) for c in cards],
        "total": len(cards),
    }
    return compat_success_tuple(
        legacy_payload=data,
        status_code=200,
        message="Cartões listados com sucesso",
        data=data,
    )


def _err_400(message: str, error_code: str) -> tuple[dict[str, Any], int]:
    return compat_error_tuple(
        legacy_payload={"error": message},
        status_code=400,
        message=message,
        error_code=error_code,
    )


def _validate_brand(payload: dict[str, Any]) -> tuple[dict[str, Any], int] | None:
    brand = payload.get("brand")
    if brand is not None and brand not in CREDIT_CARD_BRAND_VALUES:
        return _err_400(INVALID_BRAND_MESSAGE, "INVALID_BRAND")
    return None


def _validate_days(payload: dict[str, Any]) -> tuple[dict[str, Any], int] | None:
    for day_field in ("closing_day", "due_day"):
        val = payload.get(day_field)
        if val is None:
            continue
        try:
            v = int(val)
            if not (1 <= v <= 28):
                raise ValueError
        except (ValueError, TypeError):
            return _err_400(INVALID_DAY_MESSAGE, "INVALID_DAY")
    return None


def _validate_string_max(
    value: Any, *, max_len: int, message: str, error_code: str
) -> tuple[dict[str, Any], int] | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_len:
        return _err_400(message, error_code)
    return None


def _validate_benefits(payload: dict[str, Any]) -> tuple[dict[str, Any], int] | None:
    benefits = payload.get("benefits")
    if benefits is None:
        return None
    if not isinstance(benefits, list) or len(benefits) > BENEFITS_MAX_ITEMS:
        return _err_400(INVALID_BENEFITS_MESSAGE, "INVALID_BENEFITS")
    for item in benefits:
        if not isinstance(item, str) or len(item) > BENEFITS_MAX_ITEM_LENGTH:
            return _err_400(INVALID_BENEFITS_MESSAGE, "INVALID_BENEFITS")
    return None


def _validate_card_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], int] | None:
    """Run all field validators in order; return the first error or None."""
    for validator in (
        _validate_brand,
        _validate_days,
        lambda p: _validate_string_max(
            p.get("bank"),
            max_len=BANK_MAX_LENGTH,
            message=BANK_TOO_LONG_MESSAGE,
            error_code="BANK_TOO_LONG",
        ),
        lambda p: _validate_string_max(
            p.get("description"),
            max_len=DESCRIPTION_MAX_LENGTH,
            message=DESCRIPTION_TOO_LONG_MESSAGE,
            error_code="DESCRIPTION_TOO_LONG",
        ),
        _validate_benefits,
    ):
        error = validator(payload)
        if error is not None:
            return error
    return None


@credit_card_bp.route("", methods=["POST"])
@jwt_required()
@require_email_verified
def create_credit_card() -> tuple[dict[str, Any], int]:
    """Create a new credit card for the authenticated user."""
    user_id = current_user_id()
    payload = request.get_json(silent=True) or {}

    name = (payload.get("name") or "").strip()
    if not name:
        return compat_error_tuple(
            legacy_payload={"error": MISSING_NAME_MESSAGE},
            status_code=400,
            message=MISSING_NAME_MESSAGE,
            error_code="MISSING_NAME",
        )
    if len(name) > 100:
        return compat_error_tuple(
            legacy_payload={"error": NAME_TOO_LONG_MESSAGE},
            status_code=400,
            message=NAME_TOO_LONG_MESSAGE,
            error_code="NAME_TOO_LONG",
        )

    validation_error = _validate_card_payload(payload)
    if validation_error is not None:
        return validation_error

    from decimal import Decimal

    limit_raw = payload.get("limit_amount")
    limit_amount = Decimal(str(limit_raw)) if limit_raw is not None else None

    closing_day_raw = payload.get("closing_day")
    closing_day = int(closing_day_raw) if closing_day_raw is not None else None

    due_day_raw = payload.get("due_day")
    due_day = int(due_day_raw) if due_day_raw is not None else None

    card = CreditCard(
        user_id=user_id,
        name=name,
        brand=payload.get("brand") or None,
        limit_amount=limit_amount,
        closing_day=closing_day,
        due_day=due_day,
        bank=payload.get("bank") or None,
        description=payload.get("description") or None,
    )
    benefits_value = payload.get("benefits")
    if benefits_value is not None:
        card.benefits_list = list(benefits_value)
    db.session.add(card)
    db.session.commit()

    card_data = _serialize_card(card)
    return compat_success_tuple(
        legacy_payload={
            "message": "Cartão criado com sucesso",
            "credit_card": card_data,
        },
        status_code=201,
        message="Cartão criado com sucesso",
        data={"credit_card": card_data},
    )


def _coerce_text(raw: Any) -> Any:
    return raw or None


def _coerce_decimal(raw: Any) -> Any:
    from decimal import Decimal

    return Decimal(str(raw)) if raw is not None else None


def _coerce_int(raw: Any) -> Any:
    return int(raw) if raw is not None else None


def _coerce_benefits(raw: Any) -> Any:
    return list(raw) if raw is not None else None


# Maps payload keys to (attribute name, coercion fn). Keeps update logic
# table-driven so cognitive complexity stays under the Sonar/Ruff cap.
_CARD_UPDATE_FIELDS: tuple[tuple[str, str, Any], ...] = (
    ("brand", "brand", _coerce_text),
    ("limit_amount", "limit_amount", _coerce_decimal),
    ("closing_day", "closing_day", _coerce_int),
    ("due_day", "due_day", _coerce_int),
    ("bank", "bank", _coerce_text),
    ("description", "description", _coerce_text),
    ("benefits", "benefits_list", _coerce_benefits),
)


def _apply_card_updates(card: CreditCard, payload: dict[str, Any]) -> None:
    """Apply partial-update payload to an existing card.

    Only fields present in `payload` are touched. Caller commits the session.
    """
    for payload_key, attr_name, coerce in _CARD_UPDATE_FIELDS:
        if payload_key in payload:
            setattr(card, attr_name, coerce(payload.get(payload_key)))


@credit_card_bp.route("/<uuid:credit_card_id>", methods=["PUT"])
@jwt_required()
@require_email_verified
def update_credit_card(credit_card_id: UUID) -> tuple[dict[str, Any], int]:
    """Update an existing credit card belonging to the authenticated user."""
    user_id = current_user_id()
    card = CreditCard.query.filter_by(id=credit_card_id, user_id=user_id).first()
    if card is None:
        return compat_error_tuple(
            legacy_payload={"error": CREDIT_CARD_NOT_FOUND_MESSAGE},
            status_code=404,
            message=CREDIT_CARD_NOT_FOUND_MESSAGE,
            error_code="NOT_FOUND",
        )

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return compat_error_tuple(
            legacy_payload={"error": MISSING_NAME_MESSAGE},
            status_code=400,
            message=MISSING_NAME_MESSAGE,
            error_code="MISSING_NAME",
        )
    if len(name) > 100:
        return compat_error_tuple(
            legacy_payload={"error": NAME_TOO_LONG_MESSAGE},
            status_code=400,
            message=NAME_TOO_LONG_MESSAGE,
            error_code="NAME_TOO_LONG",
        )

    validation_error = _validate_card_payload(payload)
    if validation_error is not None:
        return validation_error

    card.name = name
    _apply_card_updates(card, payload)
    db.session.commit()

    card_data = _serialize_card(card)
    return compat_success_tuple(
        legacy_payload={
            "message": "Cartão atualizado com sucesso",
            "credit_card": card_data,
        },
        status_code=200,
        message="Cartão atualizado com sucesso",
        data={"credit_card": card_data},
    )


@credit_card_bp.route("/<uuid:credit_card_id>", methods=["DELETE"])
@jwt_required()
@require_email_verified
def delete_credit_card(credit_card_id: UUID) -> tuple[dict[str, Any], int]:
    """Delete a credit card belonging to the authenticated user."""
    user_id = current_user_id()
    deleted = delete_card_with_transactions(card_id=credit_card_id, user_id=user_id)
    if not deleted:
        return compat_error_tuple(
            legacy_payload={"error": CREDIT_CARD_NOT_FOUND_MESSAGE},
            status_code=404,
            message=CREDIT_CARD_NOT_FOUND_MESSAGE,
            error_code="NOT_FOUND",
        )

    return compat_success_tuple(
        legacy_payload={"message": "Cartão removido com sucesso"},
        status_code=200,
        message="Cartão removido com sucesso",
        data={},
    )
