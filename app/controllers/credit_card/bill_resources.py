"""Bill cycle + utilization REST endpoints for a credit card."""

from __future__ import annotations

# mypy: disable-error-code=untyped-decorator
import re
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from flask import request

from app.auth import current_user_id
from app.controllers.response_contract import compat_error_tuple, compat_success_tuple
from app.models.credit_card import CreditCard
from app.services.credit_card_bill_service import (
    BillCycle,
    BillSummary,
    Utilization,
    compute_bill,
    compute_utilization,
)
from app.utils.typed_decorators import typed_jwt_required as jwt_required

from .blueprint import credit_card_bp

CREDIT_CARD_NOT_FOUND_MESSAGE = "Credit card not found"
INVALID_MONTH_MESSAGE = "Field 'month' must be in YYYY-MM format (e.g. 2026-05)"
MISSING_CYCLE_CONFIG_MESSAGE = (
    "Cartão sem closing_day/due_day configurados — não é possível calcular ciclo"
)
_MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _load_owned_card(credit_card_id: UUID) -> CreditCard | None:
    user_id = current_user_id()
    card: CreditCard | None = CreditCard.query.filter_by(
        id=credit_card_id, user_id=user_id
    ).first()
    return card


def _serialize_cycle(cycle: BillCycle) -> dict[str, Any]:
    return {
        "start_date": cycle.start_date.isoformat(),
        "end_date": cycle.end_date.isoformat(),
        "due_date": cycle.due_date.isoformat(),
        "status": cycle.status,
    }


def _serialize_transaction(tx: Any) -> dict[str, Any]:
    impact_policy = getattr(tx, "impact_policy", None)
    return {
        "id": str(tx.id),
        "title": tx.title,
        "amount": str(Decimal(tx.amount)),
        "due_date": tx.due_date.isoformat() if tx.due_date else None,
        "status": tx.status.value if hasattr(tx.status, "value") else str(tx.status),
        "type": tx.type.value if hasattr(tx.type, "value") else str(tx.type),
        "impact_policy": (
            impact_policy.value
            if hasattr(impact_policy, "value")
            else str(impact_policy or "full")
        ),
    }


def _serialize_bill(bill: BillSummary) -> dict[str, Any]:
    return {
        "cycle": _serialize_cycle(bill.cycle),
        "transactions": [_serialize_transaction(tx) for tx in bill.transactions],
        "total_amount": str(bill.total_amount),
        "paid_amount": str(bill.paid_amount),
        "pending_amount": str(bill.pending_amount),
    }


def _serialize_utilization(u: Utilization) -> dict[str, Any]:
    return {
        "cycle": _serialize_cycle(u.cycle),
        "committed_amount": str(u.committed_amount),
        "available_amount": (
            str(u.available_amount) if u.available_amount is not None else None
        ),
        "limit_amount": (str(u.limit_amount) if u.limit_amount is not None else None),
        "utilization_pct": u.utilization_pct,
    }


def _resolve_month_param() -> tuple[str, tuple[dict[str, Any], int] | None]:
    """Return (month, error_response). When month is omitted, default to current."""
    raw = (request.args.get("month") or "").strip()
    if not raw:
        today = date.today()
        return f"{today.year:04d}-{today.month:02d}", None
    if not _MONTH_PATTERN.match(raw):
        return raw, compat_error_tuple(
            legacy_payload={"error": INVALID_MONTH_MESSAGE},
            status_code=400,
            message=INVALID_MONTH_MESSAGE,
            error_code="INVALID_MONTH",
        )
    return raw, None


@credit_card_bp.route("/<uuid:credit_card_id>/bill", methods=["GET"])
@jwt_required()
def get_credit_card_bill(credit_card_id: UUID) -> tuple[dict[str, Any], int]:
    """Return the bill (cycle + transactions + totals) for a given YYYY-MM."""
    card = _load_owned_card(credit_card_id)
    if card is None:
        return compat_error_tuple(
            legacy_payload={"error": CREDIT_CARD_NOT_FOUND_MESSAGE},
            status_code=404,
            message=CREDIT_CARD_NOT_FOUND_MESSAGE,
            error_code="NOT_FOUND",
        )
    if card.closing_day is None or card.due_day is None:
        return compat_error_tuple(
            legacy_payload={"error": MISSING_CYCLE_CONFIG_MESSAGE},
            status_code=400,
            message=MISSING_CYCLE_CONFIG_MESSAGE,
            error_code="MISSING_CYCLE_CONFIG",
        )

    month, error = _resolve_month_param()
    if error is not None:
        return error

    bill = compute_bill(card, month=month, today=date.today())
    data = _serialize_bill(bill)
    return compat_success_tuple(
        legacy_payload=data,
        status_code=200,
        message="Fatura calculada com sucesso",
        data=data,
    )


@credit_card_bp.route("/<uuid:credit_card_id>/utilization", methods=["GET"])
@jwt_required()
def get_credit_card_utilization(
    credit_card_id: UUID,
) -> tuple[dict[str, Any], int]:
    """Return the open-cycle utilization snapshot for a card."""
    card = _load_owned_card(credit_card_id)
    if card is None:
        return compat_error_tuple(
            legacy_payload={"error": CREDIT_CARD_NOT_FOUND_MESSAGE},
            status_code=404,
            message=CREDIT_CARD_NOT_FOUND_MESSAGE,
            error_code="NOT_FOUND",
        )
    if card.closing_day is None or card.due_day is None:
        return compat_error_tuple(
            legacy_payload={"error": MISSING_CYCLE_CONFIG_MESSAGE},
            status_code=400,
            message=MISSING_CYCLE_CONFIG_MESSAGE,
            error_code="MISSING_CYCLE_CONFIG",
        )

    utilization = compute_utilization(card, today=date.today())
    data = _serialize_utilization(utilization)
    return compat_success_tuple(
        legacy_payload=data,
        status_code=200,
        message="Utilização calculada com sucesso",
        data=data,
    )
