from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.controllers import transaction_controller_utils as utils
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.services.transaction_reference_authorization_service import (
    TransactionReferenceAuthorizationError,
)


def _build_transaction() -> Transaction:
    now = datetime(2026, 2, 11, 12, 30, 0)
    return Transaction(
        id=uuid4(),
        user_id=uuid4(),
        title="Conta",
        amount=Decimal("100.50"),
        type=TransactionType.EXPENSE,
        due_date=date(2026, 2, 10),
        status=TransactionStatus.PENDING,
        currency="BRL",
        is_recurring=False,
        is_installment=False,
        auto_settle=False,
        created_at=now,
        updated_at=now,
    )


def test_parse_helpers() -> None:
    assert utils._parse_positive_int(None, default=10, field_name="page") == 10
    assert utils._parse_positive_int("2", default=10, field_name="page") == 2
    with pytest.raises(ValueError):
        utils._parse_positive_int("0", default=1, field_name="page")
    with pytest.raises(ValueError):
        utils._parse_positive_int("abc", default=1, field_name="page")

    valid_uuid = str(uuid4())
    assert str(utils._parse_optional_uuid(valid_uuid, "tag_id")) == valid_uuid
    assert utils._parse_optional_uuid(None, "tag_id") is None
    with pytest.raises(ValueError):
        utils._parse_optional_uuid("invalid-uuid", "tag_id")

    assert utils._parse_optional_date("2026-02-10", "start_date") == date(2026, 2, 10)
    assert utils._parse_optional_date(None, "start_date") is None
    with pytest.raises(ValueError):
        utils._parse_optional_date("2026/02/10", "start_date")

    assert utils._parse_month_param("2026-02") == (2026, 2, "2026-02")
    with pytest.raises(ValueError):
        utils._parse_month_param("2026-13")
    with pytest.raises(ValueError):
        utils._parse_month_param(None)


def test_validate_recurring_payload() -> None:
    assert (
        utils._validate_recurring_payload(
            is_recurring=False,
            due_date=date(2026, 2, 10),
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )
        is None
    )
    assert (
        utils._validate_recurring_payload(
            is_recurring=True,
            due_date=None,
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28),
        )
        == "Transações recorrentes exigem 'due_date' no formato YYYY-MM-DD."
    )
    assert (
        utils._validate_recurring_payload(
            is_recurring=True,
            due_date=date(2026, 2, 10),
            start_date=date(2026, 2, 20),
            end_date=date(2026, 2, 1),
        )
        == "Parâmetro 'start_date' não pode ser maior que 'end_date'."
    )
    assert (
        utils._validate_recurring_payload(
            is_recurring=True,
            due_date=date(2026, 2, 28),
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 20),
        )
        == "Parâmetro 'due_date' deve estar entre 'start_date' e 'end_date'."
    )


def test_resolve_transaction_ordering_and_installments() -> None:
    assert str(utils._resolve_transaction_ordering("due_date", "asc")).endswith("ASC")
    assert str(utils._resolve_transaction_ordering("title", "desc")).endswith("DESC")

    with pytest.raises(ValueError):
        utils._resolve_transaction_ordering("unknown", "asc")
    with pytest.raises(ValueError):
        utils._resolve_transaction_ordering("title", "invalid")

    amounts = utils._build_installment_amounts(Decimal("100.00"), 3)
    assert len(amounts) == 3
    assert sum(amounts) == Decimal("100.00")
    with pytest.raises(ValueError):
        utils._build_installment_amounts(Decimal("100.00"), 0)


def test_compat_responses_and_internal_error(app, monkeypatch) -> None:
    with app.test_request_context("/transactions"):
        legacy_success = utils._compat_success(
            legacy_payload={"message": "ok"},
            status_code=200,
            message="ok",
            data={"a": 1},
        )
        legacy_error = utils._compat_error(
            legacy_payload={"error": "boom"},
            status_code=400,
            message="boom",
            error_code="VALIDATION_ERROR",
        )

    assert legacy_success.status_code == 200
    assert legacy_success.get_json() == {"message": "ok"}
    assert legacy_error.status_code == 400
    assert legacy_error.get_json() == {"error": "boom"}

    with app.test_request_context(
        "/transactions", headers={utils.CONTRACT_HEADER: "v2"}
    ):
        v2_success = utils._compat_success(
            legacy_payload={"message": "legacy"},
            status_code=200,
            message="ok",
            data={"a": 1},
            meta={"pagination": {"page": 1}},
        )
        v2_error = utils._compat_error(
            legacy_payload={"error": "legacy"},
            status_code=401,
            message="Token inválido.",
            error_code="UNAUTHORIZED",
        )
        invalid_token = utils._invalid_token_response()

    assert v2_success.get_json()["success"] is True
    assert v2_success.get_json()["meta"]["pagination"]["page"] == 1
    assert v2_error.get_json()["success"] is False
    assert invalid_token.get_json()["error"]["code"] == "UNAUTHORIZED"

    logged: list[str] = []
    monkeypatch.setattr(app.logger, "exception", lambda message: logged.append(message))
    with app.app_context(), app.test_request_context("/transactions"):
        internal = utils._internal_error_response(
            message="Erro interno", log_context="transaction.test"
        )

    assert internal.status_code == 500
    assert logged == ["transaction.test"]


def test_enforce_reference_ownership(monkeypatch) -> None:
    user_id = uuid4()
    tag_id = uuid4()
    account_id = uuid4()
    card_id = uuid4()
    monkeypatch.setattr(
        "app.controllers.transaction.utils.enforce_transaction_reference_ownership",
        lambda **_kwargs: None,
    )

    assert (
        utils._enforce_transaction_reference_ownership_or_error(
            user_id=user_id,
            tag_id=tag_id,
            account_id=account_id,
            credit_card_id=card_id,
        )
        is None
    )

    def _raise_error(**kwargs: object) -> None:
        raise TransactionReferenceAuthorizationError("Sem permissão para referência")

    monkeypatch.setattr(
        "app.controllers.transaction.utils.enforce_transaction_reference_ownership",
        _raise_error,
    )
    assert (
        utils._enforce_transaction_reference_ownership_or_error(
            user_id=user_id,
            tag_id=tag_id,
            account_id=account_id,
            credit_card_id=card_id,
        )
        == "Sem permissão para referência"
    )


def test_serialize_transaction_output() -> None:
    transaction = _build_transaction()
    transaction.description = "desc"
    transaction.observation = "obs"
    transaction.start_date = date(2026, 2, 1)
    transaction.end_date = date(2026, 2, 28)
    transaction.is_recurring = True
    transaction.is_installment = True
    transaction.installment_count = 2
    transaction.tag_id = uuid4()
    transaction.account_id = uuid4()
    transaction.credit_card_id = uuid4()
    transaction.source = "bank_import"
    transaction.external_id = "OFX-123"
    transaction.bank_name = "itau"

    payload = utils.serialize_transaction(transaction)
    assert payload["id"] == str(transaction.id)
    assert payload["amount"] == "100.50"
    assert payload["type"] == "expense"
    assert payload["status"] == "pending"
    assert payload["source"] == "bank_import"
    assert payload["external_id"] == "OFX-123"
    assert payload["bank_name"] == "itau"
    assert payload["start_date"] == "2026-02-01"
    assert payload["end_date"] == "2026-02-28"
    assert payload["created_at"] is not None
    assert payload["updated_at"] is not None
