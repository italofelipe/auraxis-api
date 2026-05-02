from __future__ import annotations

from typing import Any, Callable
from uuid import UUID

import pytest

from app.extensions.database import db
from app.models.account import Account
from app.models.credit_card import CreditCard
from app.models.tag import Tag
from app.models.user import User


def _graphql(
    client: Any,
    query: str,
    variables: dict[str, Any] | None = None,
    token: str | None = None,
):
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )


def _register_and_login(client: Any, suffix: str) -> str:
    register_mutation = """
    mutation Register($name: String!, $email: String!, $password: String!) {
      registerUser(name: $name, email: $email, password: $password) {
        message
      }
    }
    """
    email = f"{suffix}@email.com"
    response = _graphql(
        client,
        register_mutation,
        {"name": suffix, "email": email, "password": "StrongPass@123"},
    )
    assert response.status_code == 200
    assert "errors" not in response.get_json()

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
        {"email": email, "password": "StrongPass@123"},
    )
    assert login_response.status_code == 200
    body = login_response.get_json()
    assert body and "errors" not in body
    return str(body["data"]["login"]["token"])


def _get_user_id_by_email(app: Any, email: str) -> UUID:
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None
        return UUID(str(user.id))


def _create_wallet_and_get_id(client: Any, token: str, name: str) -> str:
    mutation = """
    mutation AddWallet($name: String!, $registerDate: String!) {
      addWalletEntry(
        name: $name,
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
        {"name": name, "registerDate": "2026-02-11"},
        token=token,
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body and "errors" not in body
    return str(body["data"]["addWalletEntry"]["item"]["id"])


@pytest.mark.parametrize(
    ("resource_field", "factory"),
    [
        ("tagId", lambda user_id: Tag(user_id=user_id, name="other-tag")),
        ("accountId", lambda user_id: Account(user_id=user_id, name="other-account")),
        (
            "creditCardId",
            lambda user_id: CreditCard(user_id=user_id, name="other-card"),
        ),
    ],
)
def test_graphql_create_transaction_denies_foreign_reference_ids(
    app: Any,
    client: Any,
    resource_field: str,
    factory: Callable[[UUID], Any],
) -> None:
    owner_token = _register_and_login(client, "graphql-owner")
    _register_and_login(client, "graphql-other")

    owner_user_id = _get_user_id_by_email(app, "graphql-owner@email.com")
    other_user_id = _get_user_id_by_email(app, "graphql-other@email.com")
    assert owner_user_id != other_user_id

    with app.app_context():
        resource = factory(other_user_id)
        db.session.add(resource)
        db.session.commit()
        foreign_id = str(resource.id)

    mutation = f"""
    mutation CreateTx(
      $title: String!,
      $amount: String!,
      $type: TransactionType!,
      $dueDate: String!,
      ${resource_field}: UUID
    ) {{
      createTransaction(
        title: $title,
        amount: $amount,
        type: $type,
        dueDate: $dueDate,
        {resource_field}: ${resource_field}
      ) {{
        message
        items {{ id }}
      }}
    }}
    """
    variables = {
        "title": "Teste authz por recurso",
        "amount": "10.00",
        "type": "EXPENSE",
        "dueDate": "2026-02-11",
        resource_field: foreign_id,
    }
    response = _graphql(client, mutation, variables, token=owner_token)
    assert response.status_code in {200, 400}
    body = response.get_json()
    assert body is not None
    assert "errors" in body
    if "data" in body:
        assert body["data"]["createTransaction"] is None
    assert body["errors"][0]["message"].startswith("Referência inválida para")


def test_graphql_investment_mutations_deny_foreign_investment_id(client: Any) -> None:
    owner_token = _register_and_login(client, "graphql-owner-investment")
    other_token = _register_and_login(client, "graphql-other-investment")
    foreign_investment_id = _create_wallet_and_get_id(
        client,
        other_token,
        "other-wallet",
    )

    add_operation_mutation = """
    mutation AddOperation($investmentId: UUID!, $executedAt: String!) {
      addInvestmentOperation(
        investmentId: $investmentId,
        operationType: "buy",
        quantity: "1",
        unitPrice: "10",
        executedAt: $executedAt
      ) {
        message
        item { id }
      }
    }
    """
    add_response = _graphql(
        client,
        add_operation_mutation,
        {"investmentId": foreign_investment_id, "executedAt": "2026-02-11"},
        token=owner_token,
    )
    add_body = add_response.get_json()
    assert add_body is not None
    assert "errors" in add_body
    if "data" in add_body:
        assert add_body["data"]["addInvestmentOperation"] is None
    assert (
        add_body["errors"][0]["message"]
        == "Você não tem permissão para acessar este investimento."
    )

    update_wallet_mutation = """
    mutation UpdateWallet($investmentId: UUID!) {
      updateWalletEntry(investmentId: $investmentId, name: "attempted-update") {
        item { id name }
      }
    }
    """
    update_response = _graphql(
        client,
        update_wallet_mutation,
        {"investmentId": foreign_investment_id},
        token=owner_token,
    )
    update_body = update_response.get_json()
    assert update_body is not None
    assert "errors" in update_body
    if "data" in update_body:
        assert update_body["data"]["updateWalletEntry"] is None
    assert (
        update_body["errors"][0]["message"]
        == "Você não tem permissão para editar este investimento."
    )

    delete_wallet_mutation = """
    mutation DeleteWallet($investmentId: UUID!) {
      deleteWalletEntry(investmentId: $investmentId) {
        ok
      }
    }
    """
    delete_response = _graphql(
        client,
        delete_wallet_mutation,
        {"investmentId": foreign_investment_id},
        token=owner_token,
    )
    delete_body = delete_response.get_json()
    assert delete_body is not None
    assert "errors" in delete_body
    if "data" in delete_body:
        assert delete_body["data"]["deleteWalletEntry"] is None
    assert (
        delete_body["errors"][0]["message"]
        == "Você não tem permissão para remover este investimento."
    )


def test_graphql_investment_queries_deny_foreign_investment_id(client: Any) -> None:
    owner_token = _register_and_login(client, "graphql-owner-investment-query")
    other_token = _register_and_login(client, "graphql-other-investment-query")
    foreign_investment_id = _create_wallet_and_get_id(
        client,
        other_token,
        "other-wallet-query",
    )

    query = """
    query ForeignInvestment($investmentId: UUID!, $date: String!) {
      investmentOperations(investmentId: $investmentId, page: 1, perPage: 10) {
        pagination { total }
      }
      investmentPosition(investmentId: $investmentId) {
        totalOperations
      }
      investmentInvestedAmount(investmentId: $investmentId, date: $date) {
        totalOperations
      }
      investmentValuation(investmentId: $investmentId) {
        investmentId
      }
    }
    """
    response = _graphql(
        client,
        query,
        {"investmentId": foreign_investment_id, "date": "2026-02-11"},
        token=owner_token,
    )
    body = response.get_json()
    assert body is not None
    assert "errors" in body
    if "data" in body:
        assert body["data"]["investmentOperations"] is None
        assert body["data"]["investmentPosition"] is None
        assert body["data"]["investmentInvestedAmount"] is None
        assert body["data"]["investmentValuation"] is None
    assert body["errors"][0]["message"] == (
        "Você não tem permissão para acessar este investimento."
    )
