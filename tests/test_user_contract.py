import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict

from app.application.services.authenticated_user_context_service import (
    AuthenticatedUserContextService,
)
from app.extensions.database import db
from app.extensions.integration_metrics import (
    build_http_observability_metrics_payload,
    reset_metrics_for_tests,
)
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.models.wallet import Wallet


def _register_and_login(client) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"user-contract-{suffix}@email.com"
    password = "StrongPass@123"

    register_response = client.post(
        "/auth/register",
        json={
            "name": f"user-{suffix}",
            "email": email,
            "password": password,
        },
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={"email": email, "password": password},
    )
    assert login_response.status_code == 200
    return login_response.get_json()["token"]


def _auth_headers(token: str, contract: str | None = None) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if contract:
        headers["X-API-Contract"] = contract
    return headers


USER_FIELDS = {
    "id",
    "name",
    "email",
    "gender",
    "birth_date",
    "monthly_income",
    "monthly_income_net",
    "net_worth",
    "monthly_expenses",
    "initial_investment",
    "monthly_investment",
    "investment_goal_date",
    "state_uf",
    "occupation",
    "investor_profile",
    "financial_objectives",
    "investor_profile_suggested",
    "profile_quiz_score",
    "taxonomy_version",
    "avatar_url",
    "onboarding_completed_at",
}

CANONICAL_USER_KEYS = {
    "identity",
    "profile",
    "financial_profile",
    "investor_profile",
    "product_context",
    "email_verification",
}

EMAIL_VERIFICATION_FIELDS = {
    "verified",
    "deadline_at",
    "required_now",
    "days_remaining",
}

IDENTITY_FIELDS = {"id", "name", "email"}
PROFILE_FIELDS = {"gender", "birth_date", "state_uf", "occupation"}
FINANCIAL_PROFILE_FIELDS = {
    "monthly_income_net",
    "monthly_expenses",
    "net_worth",
    "initial_investment",
    "monthly_investment",
    "investment_goal_date",
}
INVESTOR_PROFILE_FIELDS = {
    "declared",
    "suggested",
    "quiz_score",
    "taxonomy_version",
    "financial_objectives",
}
PRODUCT_CONTEXT_FIELDS = {"entitlements_version", "onboarding_completed_at"}

TRANSACTION_ITEM_FIELDS = {
    "id",
    "title",
    "amount",
    "type",
    "due_date",
    "status",
    "description",
    "observation",
    "is_recurring",
    "is_installment",
    "installment_count",
    "tag_id",
    "account_id",
    "credit_card_id",
    "currency",
    "created_at",
    "updated_at",
}

WALLET_ITEM_FIELDS = {
    "id",
    "name",
    "value",
    "estimated_value_on_create_date",
    "ticker",
    "quantity",
    "asset_class",
    "annual_rate",
    "target_withdraw_date",
    "register_date",
    "should_be_on_wallet",
}


def _seed_me_contract_entities(client, app) -> str:
    token = _register_and_login(client)
    auth_context = client.get(
        "/user/me",
        headers=_auth_headers(token),
    )
    assert auth_context.status_code == 200
    email = auth_context.get_json()["user"]["email"]

    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None

        transaction_one = Transaction(
            user_id=user.id,
            title="Receita recorrente",
            amount=Decimal("100.00"),
            type=TransactionType.INCOME,
            due_date=date.today(),
            status=TransactionStatus.PAID,
            currency="BRL",
            deleted=False,
        )
        transaction_two = Transaction(
            user_id=user.id,
            title="Despesa mensal",
            amount=Decimal("45.50"),
            type=TransactionType.EXPENSE,
            due_date=date.today() + timedelta(days=1),
            status=TransactionStatus.PENDING,
            currency="BRL",
            deleted=False,
        )
        wallet_one = Wallet(
            user_id=user.id,
            name="Caixa",
            value=Decimal("1000.00"),
            estimated_value_on_create_date=Decimal("1000.00"),
            quantity=1,
            should_be_on_wallet=True,
            register_date=date.today(),
        )
        wallet_two = Wallet(
            user_id=user.id,
            name="Reserva",
            value=Decimal("2000.00"),
            estimated_value_on_create_date=Decimal("2000.00"),
            quantity=1,
            should_be_on_wallet=True,
            register_date=date.today(),
        )
        db.session.add_all([transaction_one, transaction_two, wallet_one, wallet_two])
        db.session.commit()

    return token


def test_user_profile_v1_legacy_contract(client) -> None:
    token = _register_and_login(client)
    response = client.put(
        "/user/profile",
        headers=_auth_headers(token),
        json={
            "gender": "masculino",
            "investment_goal_date": (date.today() + timedelta(days=30)).isoformat(),
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "success" not in body
    assert body["message"] == "Perfil atualizado com sucesso"
    assert "data" in body


def test_user_profile_v2_contract(client) -> None:
    token = _register_and_login(client)
    response = client.put(
        "/user/profile",
        headers=_auth_headers(token, "v2"),
        json={
            "gender": "outro",
            "investment_goal_date": (date.today() + timedelta(days=60)).isoformat(),
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["message"] == "Perfil atualizado com sucesso"
    assert "user" in body["data"]


def test_user_profile_validation_error_v2_contract(client) -> None:
    token = _register_and_login(client)
    response = client.put(
        "/user/profile",
        headers=_auth_headers(token, "v2"),
        json={"investment_goal_date": (date.today() - timedelta(days=1)).isoformat()},
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_user_me_v1_legacy_contract(client) -> None:
    token = _register_and_login(client)
    response = client.get("/user/me?page=1&limit=10", headers=_auth_headers(token))

    assert response.status_code == 200
    body = response.get_json()
    assert "success" not in body
    assert "user" in body
    assert "transactions" in body
    assert "wallet" in body
    assert response.headers["Deprecation"] == "true"
    assert response.headers["X-Auraxis-Successor-Contract"] == "v3"
    assert response.headers["X-Auraxis-Successor-Endpoint"] == "/user/bootstrap"
    assert "GET /user/bootstrap" in response.headers["Warning"]


def test_user_me_v2_contract_has_meta_pagination(client) -> None:
    token = _register_and_login(client)
    response = client.get(
        "/user/me?page=1&limit=10",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert "user" in body["data"]
    assert "transactions" in body["data"]
    assert "wallet" in body["data"]
    assert "pagination" in body["meta"]
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"]


def test_user_me_v2_contract_freezes_current_field_sets(client, app) -> None:
    token = _seed_me_contract_entities(client, app)

    response = client.get(
        "/user/me?page=1&limit=10",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()

    assert set(body["data"]["user"].keys()) == USER_FIELDS
    assert body["data"]["transactions"]["items"]
    assert body["data"]["wallet"]
    assert (
        set(body["data"]["transactions"]["items"][0].keys()) == TRANSACTION_ITEM_FIELDS
    )
    assert set(body["data"]["wallet"][0].keys()) == WALLET_ITEM_FIELDS


def test_user_me_legacy_pagination_only_applies_to_transactions(client, app) -> None:
    token = _seed_me_contract_entities(client, app)

    response = client.get(
        "/user/me?page=1&limit=1",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()

    assert len(body["data"]["transactions"]["items"]) == 1
    assert body["data"]["transactions"]["total"] >= 2
    assert len(body["data"]["wallet"]) == 2


def test_user_me_invalid_status_v2_contract(client) -> None:
    token = _register_and_login(client)
    response = client.get(
        "/user/me?status=invalid",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_user_me_v3_contract_returns_canonical_context_only(client) -> None:
    token = _register_and_login(client)
    response = client.get(
        "/user/me",
        headers=_auth_headers(token, "v3"),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["message"] == "Contexto autenticado retornado com sucesso"
    assert "meta" not in body
    assert set(body["data"].keys()) == {"user"}
    assert set(body["data"]["user"].keys()) == CANONICAL_USER_KEYS
    assert set(body["data"]["user"]["identity"].keys()) == IDENTITY_FIELDS
    assert set(body["data"]["user"]["profile"].keys()) == PROFILE_FIELDS
    assert (
        set(body["data"]["user"]["financial_profile"].keys())
        == FINANCIAL_PROFILE_FIELDS
    )
    assert (
        set(body["data"]["user"]["investor_profile"].keys()) == INVESTOR_PROFILE_FIELDS
    )
    assert set(body["data"]["user"]["product_context"].keys()) == PRODUCT_CONTEXT_FIELDS
    assert (
        set(body["data"]["user"]["email_verification"].keys())
        == EMAIL_VERIFICATION_FIELDS
    )
    assert "monthly_income" not in body["data"]["user"]["financial_profile"]
    assert "transactions" not in body["data"]["user"]
    assert "wallet" not in body["data"]["user"]
    assert "Deprecation" not in response.headers
    assert "Sunset" not in response.headers


def test_user_me_v3_contract_does_not_load_wallet_entries(client, monkeypatch) -> None:
    token = _register_and_login(client)

    def _raise_wallet_query(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("wallet preview should not be loaded for /user/me v3")

    monkeypatch.setattr(
        AuthenticatedUserContextService,
        "build_wallet_entries",
        _raise_wallet_query,
    )

    response = client.get("/user/me", headers=_auth_headers(token, "v3"))

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True


def test_user_me_legacy_contract_emits_deprecation_metrics(client) -> None:
    reset_metrics_for_tests()
    token = _register_and_login(client)

    response = client.get(
        "/user/me?page=1&limit=10",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200

    payload = build_http_observability_metrics_payload()
    assert payload["summary"]["user_me_legacy"] >= 1
    assert payload["summary"]["user_me_legacy_with_collection_semantics"] >= 1


def test_user_me_v3_contract_rejects_collection_semantics(client) -> None:
    token = _register_and_login(client)
    response = client.get(
        "/user/me?page=1&limit=10",
        headers=_auth_headers(token, "v3"),
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["message"] == (
        "O contrato canônico de '/user/me' não aceita paginação nem filtros de "
        "coleção. Use '/transactions' ou o bootstrap dedicado."
    )


def test_user_me_masks_unexpected_value_error(client, monkeypatch) -> None:
    token = _register_and_login(client)

    def _raise_unexpected_value_error(*_args: object, **_kwargs: object) -> int:
        raise ValueError("sqlalchemy internal error leaked")

    monkeypatch.setattr(
        "app.controllers.user_controller._parse_positive_int",
        _raise_unexpected_value_error,
    )

    response = client.get(
        "/user/me?page=1&limit=10",
        headers=_auth_headers(token, "v2"),
    )
    assert response.status_code == 400
    body = response.get_json()
    serialized = str(body)
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["message"] == "Parâmetros de paginação inválidos."
    assert "sqlalchemy internal error leaked" not in serialized
