from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from graphql import GraphQLError

from app.graphql import auth as graphql_auth
from app.graphql import errors as graphql_errors
from app.graphql import schema_utils
from app.graphql.mutations.investment_operation import InvestmentOperationError
from app.graphql.queries.investment import (
    InvestmentOperationService,
    PortfolioHistoryService,
    PortfolioValuationService,
)


def _graphql(
    client: Any,
    query: str,
    variables: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )


def _register_and_login_graphql(client: Any, suffix: str) -> str:
    register_mutation = """
    mutation Register($name: String!, $email: String!, $password: String!) {
      registerUser(name: $name, email: $email, password: $password) {
        message
      }
    }
    """
    register_response = _graphql(
        client,
        register_mutation,
        {
            "name": suffix,
            "email": f"{suffix}@email.com",
            "password": "StrongPass@123",
        },
    )
    assert register_response.status_code == 200
    assert "errors" not in register_response.get_json()

    login_mutation = """
    mutation Login($email: String!, $password: String!) {
      login(email: $email, password: $password) {
        token
      }
    }
    """
    login_response = _graphql(
        client,
        login_mutation,
        {"email": f"{suffix}@email.com", "password": "StrongPass@123"},
    )
    assert login_response.status_code == 200
    login_body = login_response.get_json()
    assert "errors" not in login_body
    token = login_body["data"]["login"]["token"]
    assert token
    return token


def _first_error_code(response: Any) -> str:
    body = response.get_json()
    assert body and "errors" in body
    return body["errors"][0]["extensions"]["code"]


def _create_wallet_entry(client: Any, token: str, *, suffix: str) -> str:
    mutation = """
    mutation AddWallet($name: String!, $registerDate: String!) {
      addWalletEntry(
        name: $name,
        value: 1000,
        registerDate: $registerDate,
        shouldBeOnWallet: true
      ) {
        item { id name }
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        variables={"name": f"Wallet {suffix}", "registerDate": "2026-02-19"},
        token=token,
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "errors" not in body
    return body["data"]["addWalletEntry"]["item"]["id"]


def test_graphql_login_invalid_credentials_returns_unauthorized_code(
    client: Any,
) -> None:
    _register_and_login_graphql(client, "graphql-auth-base")
    mutation = """
    mutation Login($email: String!, $password: String!) {
      login(email: $email, password: $password) {
        token
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        variables={"email": "graphql-auth-base@email.com", "password": "wrong"},
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "UNAUTHORIZED"


def test_graphql_duplicate_ticker_returns_conflict_code(client: Any) -> None:
    token = _register_and_login_graphql(client, "graphql-ticker-conflict")
    mutation = """
    mutation AddTicker($symbol: String!, $quantity: Float!) {
      addTicker(symbol: $symbol, quantity: $quantity) {
        item { id symbol quantity }
      }
    }
    """
    first = _graphql(
        client,
        mutation,
        variables={"symbol": "PETR4", "quantity": 1},
        token=token,
    )
    assert first.status_code == 200
    assert "errors" not in first.get_json()

    second = _graphql(
        client,
        mutation,
        variables={"symbol": "PETR4", "quantity": 1},
        token=token,
    )
    assert second.status_code in {200, 400}
    assert _first_error_code(second) == "CONFLICT"


def test_graphql_wallet_validation_returns_validation_code(client: Any) -> None:
    token = _register_and_login_graphql(client, "graphql-wallet-validation")
    mutation = """
    mutation AddWallet($registerDate: String!) {
      addWalletEntry(
        name: "Reserva",
        value: 1000,
        registerDate: $registerDate,
        shouldBeOnWallet: true
      ) {
        item { id }
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        variables={"registerDate": "2026/02/19"},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "VALIDATION_ERROR"


def test_graphql_transaction_delete_forbidden_returns_forbidden_code(
    client: Any,
) -> None:
    owner_token = _register_and_login_graphql(client, "graphql-tx-owner")
    intruder_token = _register_and_login_graphql(client, "graphql-tx-intruder")

    create_mutation = """
    mutation CreateTx($dueDate: String!) {
      createTransaction(
        title: "Conta",
        amount: "100.00",
        type: EXPENSE,
        dueDate: $dueDate
      ) {
        items { id }
      }
    }
    """
    create_response = _graphql(
        client,
        create_mutation,
        variables={"dueDate": date.today().isoformat()},
        token=owner_token,
    )
    assert create_response.status_code == 200
    create_body = create_response.get_json()
    assert "errors" not in create_body
    transaction_id = create_body["data"]["createTransaction"]["items"][0]["id"]

    delete_mutation = """
    mutation DeleteTx($transactionId: UUID!) {
      deleteTransaction(transactionId: $transactionId) {
        ok
        message
      }
    }
    """
    delete_response = _graphql(
        client,
        delete_mutation,
        variables={"transactionId": transaction_id},
        token=intruder_token,
    )
    assert delete_response.status_code in {200, 400}
    assert _first_error_code(delete_response) == "FORBIDDEN"


def test_graphql_investment_not_found_returns_not_found_code(client: Any) -> None:
    token = _register_and_login_graphql(client, "graphql-investment-not-found")
    query = """
    query Summary($investmentId: UUID!) {
      investmentOperationSummary(investmentId: $investmentId) {
        totalOperations
      }
    }
    """
    response = _graphql(
        client,
        query,
        variables={"investmentId": str(uuid4())},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "NOT_FOUND"


def test_graphql_create_transaction_empty_due_date_returns_validation_code(
    client: Any,
) -> None:
    token = _register_and_login_graphql(client, "graphql-create-empty-due-date")
    mutation = """
    mutation CreateTx($dueDate: String!) {
      createTransaction(
        title: "Conta",
        amount: "100.00",
        type: EXPENSE,
        dueDate: $dueDate
      ) {
        message
      }
    }
    """
    response = _graphql(client, mutation, {"dueDate": ""}, token=token)
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "VALIDATION_ERROR"


def test_graphql_create_transaction_recurring_missing_window_returns_validation_code(
    client: Any,
) -> None:
    token = _register_and_login_graphql(client, "graphql-recurring-validation")
    mutation = """
    mutation CreateTx($dueDate: String!) {
      createTransaction(
        title: "Conta",
        amount: "100.00",
        type: EXPENSE,
        dueDate: $dueDate,
        isRecurring: true
      ) {
        message
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"dueDate": date.today().isoformat()},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "VALIDATION_ERROR"


def test_graphql_create_transaction_negative_installment_count_returns_validation_code(
    client: Any,
) -> None:
    token = _register_and_login_graphql(client, "graphql-installment-validation")
    mutation = """
    mutation CreateTx($dueDate: String!) {
      createTransaction(
        title: "Compra",
        amount: "500.00",
        type: EXPENSE,
        dueDate: $dueDate,
        isInstallment: true,
        installmentCount: -1
      ) {
        message
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"dueDate": date.today().isoformat()},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "VALIDATION_ERROR"


def test_graphql_due_range_missing_period_returns_validation_code(client: Any) -> None:
    token = _register_and_login_graphql(client, "graphql-due-range-missing-period")
    query = """
    query DueRange {
      transactionDueRange(page: 1, perPage: 10) {
        pagination { total }
      }
    }
    """
    response = _graphql(client, query, token=token)
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "VALIDATION_ERROR"


def test_graphql_delete_transaction_not_found_returns_not_found_code(
    client: Any,
) -> None:
    token = _register_and_login_graphql(client, "graphql-tx-not-found")
    mutation = """
    mutation DeleteTx($transactionId: UUID!) {
      deleteTransaction(transactionId: $transactionId) {
        ok
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"transactionId": str(uuid4())},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "NOT_FOUND"


def test_graphql_update_wallet_invalid_partial_payload_returns_validation_code(
    client: Any,
) -> None:
    token = _register_and_login_graphql(client, "graphql-wallet-update-validation")
    investment_id = _create_wallet_entry(client, token, suffix="update-invalid")
    mutation = """
    mutation UpdateWallet($investmentId: UUID!, $registerDate: String!) {
      updateWalletEntry(investmentId: $investmentId, registerDate: $registerDate) {
        item { id }
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"investmentId": investment_id, "registerDate": "19/02/2026"},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "VALIDATION_ERROR"


def test_graphql_add_investment_operation_invalid_payload_returns_validation_code(
    client: Any,
) -> None:
    token = _register_and_login_graphql(client, "graphql-op-create-validation")
    investment_id = _create_wallet_entry(client, token, suffix="op-create")
    mutation = """
    mutation AddOperation($investmentId: UUID!, $executedAt: String!) {
      addInvestmentOperation(
        investmentId: $investmentId,
        operationType: "buy",
        quantity: "2",
        unitPrice: "10.5",
        executedAt: $executedAt
      ) {
        message
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"investmentId": investment_id, "executedAt": "2026/02/19"},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "VALIDATION_ERROR"


def test_graphql_update_investment_operation_not_found_returns_not_found_code(
    client: Any,
) -> None:
    token = _register_and_login_graphql(client, "graphql-op-update-not-found")
    investment_id = _create_wallet_entry(client, token, suffix="op-update")
    mutation = """
    mutation UpdateOperation($investmentId: UUID!, $operationId: UUID!) {
      updateInvestmentOperation(
        investmentId: $investmentId,
        operationId: $operationId,
        notes: "update"
      ) {
        message
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"investmentId": investment_id, "operationId": str(uuid4())},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "NOT_FOUND"


def test_graphql_delete_investment_operation_not_found_returns_not_found_code(
    client: Any,
) -> None:
    token = _register_and_login_graphql(client, "graphql-op-delete-not-found")
    investment_id = _create_wallet_entry(client, token, suffix="op-delete")
    mutation = """
    mutation DeleteOperation($investmentId: UUID!, $operationId: UUID!) {
      deleteInvestmentOperation(
        investmentId: $investmentId,
        operationId: $operationId
      ) {
        ok
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {"investmentId": investment_id, "operationId": str(uuid4())},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "NOT_FOUND"


def test_graphql_investment_query_service_errors_use_public_codes(
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _register_and_login_graphql(client, "graphql-investment-query-errors")
    investment_id = _create_wallet_entry(client, token, suffix="query-errors")

    def _raise_not_found(*_args: Any, **_kwargs: Any) -> Any:
        raise InvestmentOperationError(
            message="Operação não encontrada",
            code="NOT_FOUND",
            status_code=404,
        )

    monkeypatch.setattr(InvestmentOperationService, "list_operations", _raise_not_found)
    monkeypatch.setattr(InvestmentOperationService, "get_summary", _raise_not_found)
    monkeypatch.setattr(InvestmentOperationService, "get_position", _raise_not_found)
    monkeypatch.setattr(
        InvestmentOperationService,
        "get_invested_amount_by_date",
        _raise_not_found,
    )
    monkeypatch.setattr(
        PortfolioValuationService,
        "get_investment_current_valuation",
        _raise_not_found,
    )
    monkeypatch.setattr(
        PortfolioHistoryService,
        "get_history",
        lambda self, **kwargs: (_ for _ in ()).throw(ValueError("invalid range")),
    )

    operations_query = """
    query Operations($investmentId: UUID!) {
      investmentOperations(investmentId: $investmentId, page: 1, perPage: 10) {
        pagination { total }
      }
    }
    """
    summary_query = """
    query Summary($investmentId: UUID!) {
      investmentOperationSummary(investmentId: $investmentId) {
        totalOperations
      }
    }
    """
    position_query = """
    query Position($investmentId: UUID!) {
      investmentPosition(investmentId: $investmentId) {
        totalOperations
      }
    }
    """
    amount_query = """
    query Amount($investmentId: UUID!, $date: String!) {
      investmentInvestedAmount(investmentId: $investmentId, date: $date) {
        date
      }
    }
    """
    valuation_query = """
    query Valuation($investmentId: UUID!) {
      investmentValuation(investmentId: $investmentId) {
        investmentId
      }
    }
    """
    history_query = """
    query History {
      portfolioValuationHistory(startDate: "2026-02-20", finalDate: "2026-02-19") {
        summary { totalPoints }
      }
    }
    """

    for query, variables, expected in [
        (operations_query, {"investmentId": investment_id}, "NOT_FOUND"),
        (summary_query, {"investmentId": investment_id}, "NOT_FOUND"),
        (position_query, {"investmentId": investment_id}, "NOT_FOUND"),
        (
            amount_query,
            {"investmentId": investment_id, "date": "2026-02-19"},
            "NOT_FOUND",
        ),
        (valuation_query, {"investmentId": investment_id}, "NOT_FOUND"),
        (history_query, None, "VALIDATION_ERROR"),
    ]:
        response = _graphql(client, query, variables=variables, token=token)
        assert response.status_code in {200, 400}
        assert _first_error_code(response) == expected


def test_graphql_invested_amount_requires_date_value(client: Any) -> None:
    token = _register_and_login_graphql(client, "graphql-invested-date-required")
    investment_id = _create_wallet_entry(client, token, suffix="date-required")
    query = """
    query Amount($investmentId: UUID!, $date: String!) {
      investmentInvestedAmount(investmentId: $investmentId, date: $date) {
        date
      }
    }
    """
    response = _graphql(
        client,
        query,
        variables={"investmentId": investment_id, "date": ""},
        token=token,
    )
    assert response.status_code in {200, 400}
    assert _first_error_code(response) == "VALIDATION_ERROR"


def test_graphql_catalog_helpers_cover_fallback_and_mapping_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert graphql_errors.to_public_graphql_code("unknown_code") == "VALIDATION_ERROR"

    public_error = graphql_errors.build_public_graphql_error(
        "too many",
        code="TOO_MANY_ATTEMPTS",
        retry_after_seconds=30,
    )
    assert public_error.extensions["code"] == "TOO_MANY_ATTEMPTS"
    assert public_error.extensions["retry_after_seconds"] == 30

    mapped_error = graphql_errors.from_mapped_validation_exception(
        ValueError("bad request"),
        fallback_message="fallback validation",
    )
    assert mapped_error.extensions["code"] == "VALIDATION_ERROR"

    monkeypatch.setattr(
        graphql_auth,
        "get_current_user_optional",
        lambda: None,
    )
    with pytest.raises(GraphQLError) as exc_info:
        graphql_auth.get_current_user_required()
    assert "Token inválido ou ausente." in str(exc_info.value)


def test_parse_month_value_error_maps_to_validation_code() -> None:
    with pytest.raises(GraphQLError) as exc_info:
        schema_utils._parse_month("invalid")
    error = exc_info.value
    assert getattr(error, "extensions", {}).get("code") == "VALIDATION_ERROR"
