from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.application.services.user_profile_service import (
    VALID_INVESTOR_PROFILES,
    update_user_profile,
)
from app.models.user import User


def _register_and_login(client) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"profile-{suffix}@email.com"
    password = "StrongPass@123"

    register = client.post(
        "/auth/register",
        json={
            "name": f"profile-{suffix}",
            "email": email,
            "password": password,
        },
    )
    assert register.status_code == 201

    login = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    return login.get_json()["token"]


def _graphql(
    client,
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


def _register_and_login_graphql(client) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"profile-gql-{suffix}@email.com"
    password = "StrongPass@123"

    register_mutation = """
    mutation Register($name: String!, $email: String!, $password: String!) {
      registerUser(name: $name, email: $email, password: $password) {
        message
      }
    }
    """
    register = _graphql(
        client,
        register_mutation,
        {"name": f"profile-gql-{suffix}", "email": email, "password": password},
    )
    assert register.status_code == 200
    assert "errors" not in register.get_json()

    login_mutation = """
    mutation Login($email: String!, $password: String!) {
      login(email: $email, password: $password) {
        token
      }
    }
    """
    login = _graphql(
        client,
        login_mutation,
        {"email": email, "password": password},
    )
    assert login.status_code == 200
    login_body = login.get_json()
    assert "errors" not in login_body
    token = login_body["data"]["login"]["token"]
    assert token
    return token


def test_update_user_profile_service_valid_investor_profile() -> None:
    user = User(name="Test User", email="user@test.com", password="hash")
    for profile in VALID_INVESTOR_PROFILES:
        result = update_user_profile(user, {"investor_profile": profile})
        assert result["error"] is None
        assert user.investor_profile == profile


def test_update_user_profile_service_invalid_investor_profile() -> None:
    user = User(name="Test User", email="user2@test.com", password="hash")
    result = update_user_profile(user, {"investor_profile": "agressivo"})
    assert result["error"] is not None
    assert user.investor_profile is None


def test_rest_update_profile_accepts_valid_investor_profile_and_v1_fields(
    client,
) -> None:
    token = _register_and_login(client)
    response = client.put(
        "/user/profile",
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
        json={
            "investor_profile": "explorador",
            "state_uf": "sp",
            "occupation": "Engenheiro",
            "financial_objectives": "Aposentar cedo",
            "monthly_income_net": "7500.00",
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    user = body["data"]["user"]
    assert user["investor_profile"] == "explorador"
    assert user["state_uf"] == "SP"
    assert user["occupation"] == "Engenheiro"
    assert user["financial_objectives"] == "Aposentar cedo"
    assert user["monthly_income"] == 7500.0
    assert user["monthly_income_net"] == 7500.0


def test_rest_update_profile_rejects_invalid_investor_profile(client) -> None:
    token = _register_and_login(client)
    response = client.put(
        "/user/profile",
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
        json={"investor_profile": "agressivo"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["message"] == "Validation error"
    assert "investor_profile" in str(body["error"]["details"])


def test_rest_get_profile_returns_reduced_payload(client) -> None:
    token = _register_and_login(client)
    response = client.get(
        "/user/profile",
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert "user" in body["data"]
    assert "transactions" not in body["data"]
    assert "wallet" not in body["data"]


def test_rest_update_profile_rejects_expenses_above_income(client) -> None:
    token = _register_and_login(client)
    response = client.put(
        "/user/profile",
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
        json={
            "monthly_income": "3000.00",
            "monthly_expenses": "3500.00",
        },
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "Gastos mensais não podem ser maiores que a renda mensal." in str(
        body["error"]["details"]
    )


def test_rest_update_profile_rejects_investment_above_capacity(client) -> None:
    token = _register_and_login(client)
    response = client.put(
        "/user/profile",
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
        json={
            "monthly_income": "5000.00",
            "monthly_expenses": "3000.00",
            "monthly_investment": "2500.00",
        },
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "Investimento mensal não pode ser maior que a capacidade de aporte" in str(
        body["error"]["details"]
    )


def test_rest_update_profile_emits_audit_event(client, caplog) -> None:
    token = _register_and_login(client)
    response = client.put(
        "/user/profile",
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
        json={
            "state_uf": "sp",
            "occupation": "QA",
            "investor_profile": "explorador",
        },
    )
    assert response.status_code == 200
    messages = [record.message for record in caplog.records]
    assert any("event=user.profile_update" in message for message in messages)
    assert any(
        "changed_fields=investor_profile,occupation,state_uf" in message
        for message in messages
    )


def test_rest_register_accepts_optional_investor_profile(client, app) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"onboarding-{suffix}@email.com"
    response = client.post(
        "/auth/register",
        json={
            "name": f"onboarding-{suffix}",
            "email": email,
            "password": "StrongPass@123",
            "investor_profile": "conservador",
        },
    )
    assert response.status_code == 201

    with app.app_context():
        stored = User.query.filter_by(email=email).first()
        assert stored is not None
        assert stored.investor_profile == "conservador"


def test_graphql_update_profile_accepts_valid_investor_profile(client) -> None:
    token = _register_and_login_graphql(client)

    mutation = """
    mutation UpdateProfile {
      updateUserProfile(
        investorProfile: "entusiasta"
        stateUf: "rj"
        occupation: "Arquiteto"
        financialObjectives: "Independência financeira"
        monthlyIncomeNet: 9500
      ) {
        user {
          investorProfile
          stateUf
          occupation
          financialObjectives
          monthlyIncome
          monthlyIncomeNet
        }
      }
    }
    """
    response = _graphql(client, mutation, token=token)
    assert response.status_code == 200
    body = response.get_json()
    assert "errors" not in body
    user = body["data"]["updateUserProfile"]["user"]
    assert user["investorProfile"] == "entusiasta"
    assert user["stateUf"] == "RJ"
    assert user["occupation"] == "Arquiteto"
    assert user["financialObjectives"] == "Independência financeira"
    assert Decimal(user["monthlyIncome"]) == Decimal("9500")
    assert Decimal(user["monthlyIncomeNet"]) == Decimal("9500")


def test_graphql_update_profile_rejects_invalid_investor_profile(client) -> None:
    token = _register_and_login_graphql(client)

    mutation = """
    mutation UpdateProfileInvalid {
      updateUserProfile(investorProfile: "agressivo") {
        user { id }
      }
    }
    """
    response = _graphql(client, mutation, token=token)
    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["updateUserProfile"] is None
    assert body["errors"][0]["extensions"]["code"] == "VALIDATION_ERROR"
    assert "Perfil do investidor inválido" in body["errors"][0]["message"]


def test_graphql_update_profile_rejects_expenses_above_income(client) -> None:
    token = _register_and_login_graphql(client)
    mutation = """
    mutation InvalidCoherence {
      updateUserProfile(
        monthlyIncome: 2000
        monthlyExpenses: 2500
      ) {
        user { id }
      }
    }
    """
    response = _graphql(client, mutation, token=token)
    assert response.status_code == 200
    body = response.get_json()
    assert body["data"]["updateUserProfile"] is None
    assert body["errors"][0]["extensions"]["code"] == "VALIDATION_ERROR"
    assert (
        "Gastos mensais não podem ser maiores que a renda mensal."
        in body["errors"][0]["message"]
    )


def test_graphql_register_accepts_optional_investor_profile(client) -> None:
    suffix = uuid.uuid4().hex[:8]
    email = f"register-gql-{suffix}@email.com"
    mutation = """
    mutation Register(
      $name: String!
      $email: String!
      $password: String!
      $investorProfile: String
    ) {
      registerUser(
        name: $name
        email: $email
        password: $password
        investorProfile: $investorProfile
      ) {
        message
        user {
          email
          investorProfile
        }
      }
    }
    """
    response = _graphql(
        client,
        mutation,
        {
            "name": f"register-gql-{suffix}",
            "email": email,
            "password": "StrongPass@123",
            "investorProfile": "conservador",
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert "errors" not in body
    assert body["data"]["registerUser"]["user"]["email"] == email
    assert body["data"]["registerUser"]["user"]["investorProfile"] == "conservador"
