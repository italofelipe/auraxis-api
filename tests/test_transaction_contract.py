import uuid
from datetime import date, timedelta
from typing import Any, Dict
from uuid import UUID

from flask_jwt_extended import decode_token

from app.extensions.database import db
from app.models.credit_card import CreditCard
from app.models.tag import Tag


def _register_and_login(client) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"transaction-{suffix}@email.com"
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
        json={
            "email": email,
            "password": password,
        },
    )
    assert login_response.status_code == 200
    return login_response.get_json()["token"]


def _auth_headers(token: str, contract: str | None = None) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if contract:
        headers["X-API-Contract"] = contract
    return headers


def _transaction_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": "Conta de luz",
        "amount": "150.50",
        "type": "expense",
        "due_date": date.today().isoformat(),
    }
    payload.update(overrides)
    return payload


def test_transaction_create_v1_legacy_contract(client) -> None:
    token = _register_and_login(client)

    response = client.post(
        "/transactions",
        json=_transaction_payload(),
        headers=_auth_headers(token),
    )

    assert response.status_code == 201
    body = response.get_json()
    assert "success" not in body
    assert body["message"] == "Transação criada com sucesso"
    assert "transaction" in body


def test_transaction_create_v2_contract(client) -> None:
    token = _register_and_login(client)

    response = client.post(
        "/transactions",
        json=_transaction_payload(),
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["success"] is True
    assert body["message"] == "Transação criada com sucesso"
    assert "transaction" in body["data"]
    assert body["data"]["transaction"][0]["impact_policy"] == "full"


def test_transaction_impact_policy_roundtrip_and_installments_v2_contract(
    client,
) -> None:
    token = _register_and_login(client)

    created = client.post(
        "/transactions",
        json=_transaction_payload(
            title="Compra isolada do cartão",
            impact_policy="cards_only",
        ),
        headers=_auth_headers(token, "v2"),
    )
    assert created.status_code == 201
    transaction = created.get_json()["data"]["transaction"][0]
    assert transaction["impact_policy"] == "cards_only"

    patched = client.patch(
        f"/transactions/{transaction['id']}",
        json={"impact_policy": "planned_until_bill"},
        headers=_auth_headers(token, "v2"),
    )
    assert patched.status_code == 200
    assert patched.get_json()["data"]["transaction"]["impact_policy"] == (
        "planned_until_bill"
    )

    installments = client.post(
        "/transactions",
        json=_transaction_payload(
            title="Compra parcelada isolada",
            amount="300.00",
            is_installment=True,
            installment_count=3,
            impact_policy="cards_only",
        ),
        headers=_auth_headers(token, "v2"),
    )
    assert installments.status_code == 201
    rows = installments.get_json()["data"]["transactions"]
    assert len(rows) == 3
    assert {row["impact_policy"] for row in rows} == {"cards_only"}


def test_transaction_create_rejects_invalid_impact_policy_v2_contract(client) -> None:
    token = _register_and_login(client)

    response = client.post(
        "/transactions",
        json=_transaction_payload(impact_policy="dashboard_and_cards_but_spicy"),
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 400


def test_transaction_list_and_summary_v2_contract(client) -> None:
    token = _register_and_login(client)
    create_response = client.post(
        "/transactions",
        json=_transaction_payload(),
        headers=_auth_headers(token, "v2"),
    )
    assert create_response.status_code == 201

    list_response = client.get(
        "/transactions",
        headers=_auth_headers(token, "v2"),
    )
    assert list_response.status_code == 200
    list_body = list_response.get_json()
    assert list_body["success"] is True
    assert "transactions" in list_body["data"]
    assert "pagination" in list_body["meta"]

    month_ref = date.today().strftime("%Y-%m")
    summary_response = client.get(
        f"/transactions/summary?month={month_ref}&page=1&per_page=5",
        headers=_auth_headers(token, "v2"),
    )
    assert summary_response.status_code == 200
    summary_body = summary_response.get_json()
    assert summary_body["success"] is True
    assert "income_total" in summary_body["data"]
    assert "expense_total" in summary_body["data"]
    assert "pagination" in summary_body["meta"]


def test_transaction_patch_is_canonical_and_put_is_compatibility_v2_contract(
    client,
) -> None:
    token = _register_and_login(client)
    created = client.post(
        "/transactions",
        json=_transaction_payload(),
        headers=_auth_headers(token, "v2"),
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    patch_response = client.patch(
        f"/transactions/{transaction_id}",
        json={"title": "Conta de luz patch"},
        headers=_auth_headers(token, "v2"),
    )
    assert patch_response.status_code == 200
    patch_body = patch_response.get_json()
    assert patch_body["success"] is True
    assert patch_body["data"]["transaction"]["title"] == "Conta de luz patch"
    assert patch_response.headers.get("Deprecation") is None

    put_response = client.put(
        f"/transactions/{transaction_id}",
        json={"description": "Compatibilidade PUT"},
        headers=_auth_headers(token, "v2"),
    )
    assert put_response.status_code == 200
    assert put_response.headers["Deprecation"] == "true"
    assert put_response.headers["X-Auraxis-Successor-Method"] == "PATCH"
    put_body = put_response.get_json()
    assert put_body["success"] is True
    assert put_body["data"]["transaction"]["description"] == "Compatibilidade PUT"


def test_transaction_summary_missing_month_v2_contract(client) -> None:
    token = _register_and_login(client)

    response = client.get(
        "/transactions/summary",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_dashboard_overview_v2_contract(client) -> None:
    token = _register_and_login(client)
    month_ref = date.today().strftime("%Y-%m")

    with client.application.app_context():
        user_id = UUID(decode_token(token)["sub"])
        food_tag = Tag(user_id=user_id, name="Alimentacao")
        home_tag = Tag(user_id=user_id, name="Moradia")
        db.session.add_all([food_tag, home_tag])
        db.session.commit()
        food_tag_id = str(food_tag.id)
        home_tag_id = str(home_tag.id)

    payloads = [
        _transaction_payload(
            title="Salario",
            type="income",
            status="paid",
            amount="1000.00",
            due_date=date.today().isoformat(),
        ),
        _transaction_payload(
            title="Mercado",
            type="expense",
            status="pending",
            amount="100.00",
            tag_id=food_tag_id,
            due_date=date.today().isoformat(),
        ),
        _transaction_payload(
            title="Aluguel",
            type="expense",
            status="paid",
            amount="300.00",
            tag_id=home_tag_id,
            due_date=date.today().isoformat(),
        ),
        _transaction_payload(
            title="Cafe",
            type="expense",
            status="cancelled",
            amount="50.00",
            due_date=date.today().isoformat(),
        ),
        _transaction_payload(
            title="Compra isolada",
            type="expense",
            status="paid",
            amount="700.00",
            due_date=date.today().isoformat(),
            impact_policy="cards_only",
        ),
    ]
    for payload in payloads:
        created = client.post(
            "/transactions",
            json=payload,
            headers=_auth_headers(token, "v2"),
        )
        assert created.status_code == 201

    response = client.get(
        f"/dashboard/overview?month={month_ref}",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["month"] == month_ref
    assert body["data"]["totals"]["income_total"] == 1000.0
    assert body["data"]["totals"]["expense_total"] == 450.0
    assert body["data"]["totals"]["balance"] == 550.0
    assert body["data"]["counts"]["total_transactions"] == 4
    assert body["data"]["counts"]["income_transactions"] == 1
    assert body["data"]["counts"]["expense_transactions"] == 3
    assert body["data"]["counts"]["status"]["paid"] == 2
    assert body["data"]["counts"]["status"]["pending"] == 1
    assert body["data"]["counts"]["status"]["cancelled"] == 1
    assert body["data"]["top_categories"]["expense"][0]["category_name"] == "Moradia"
    assert body["data"]["top_categories"]["expense"][0]["total_amount"] == 300.0


def test_transaction_dashboard_legacy_contract(client) -> None:
    token = _register_and_login(client)
    month_ref = date.today().strftime("%Y-%m")

    created = client.post(
        "/transactions",
        json=_transaction_payload(type="expense", amount="100.00"),
        headers=_auth_headers(token),
    )
    assert created.status_code == 201

    response = client.get(
        f"/transactions/dashboard?month={month_ref}",
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["X-Auraxis-Successor-Endpoint"] == "/dashboard/overview"
    body = response.get_json()
    assert "success" not in body
    assert body["month"] == month_ref
    assert "income_total" in body
    assert "expense_total" in body
    assert "balance" in body
    assert "counts" in body
    assert "top_expense_categories" in body
    assert "top_income_categories" in body


def test_transaction_dashboard_invalid_month_v2_contract(client) -> None:
    token = _register_and_login(client)

    response = client.get(
        "/dashboard/overview?month=2026-13",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_delete_restore_force_v2_contract(client) -> None:
    token = _register_and_login(client)
    create_response = client.post(
        "/transactions",
        json=_transaction_payload(),
        headers=_auth_headers(token, "v2"),
    )
    assert create_response.status_code == 201
    transaction_id = create_response.get_json()["data"]["transaction"][0]["id"]

    delete_response = client.delete(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
    )
    assert delete_response.status_code == 200
    delete_body = delete_response.get_json()
    assert delete_body["success"] is True

    restore_response = client.patch(
        f"/transactions/restore/{transaction_id}",
        headers=_auth_headers(token, "v2"),
    )
    assert restore_response.status_code == 200
    restore_body = restore_response.get_json()
    assert restore_body["success"] is True

    delete_again_response = client.delete(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
    )
    assert delete_again_response.status_code == 200

    force_response = client.delete(
        f"/transactions/{transaction_id}/force",
        headers=_auth_headers(token, "v2"),
    )
    assert force_response.status_code == 200
    force_body = force_response.get_json()
    assert force_body["success"] is True


def test_transaction_list_filters_and_pagination_v2_contract(client) -> None:
    token = _register_and_login(client)

    today = date.today()
    responses = [
        client.post(
            "/transactions",
            json=_transaction_payload(
                title="Salario",
                type="income",
                status="paid",
                due_date=(today - timedelta(days=1)).isoformat(),
            ),
            headers=_auth_headers(token, "v2"),
        ),
        client.post(
            "/transactions",
            json=_transaction_payload(
                title="Mercado",
                type="expense",
                status="pending",
                due_date=today.isoformat(),
            ),
            headers=_auth_headers(token, "v2"),
        ),
        client.post(
            "/transactions",
            json=_transaction_payload(
                title="Freelance",
                type="income",
                status="pending",
                due_date=(today + timedelta(days=1)).isoformat(),
            ),
            headers=_auth_headers(token, "v2"),
        ),
    ]
    assert all(response.status_code == 201 for response in responses)

    response = client.get(
        (
            "/transactions?page=1&per_page=1&type=income&status=pending"
            f"&start_date={today.isoformat()}"
            f"&end_date={(today + timedelta(days=2)).isoformat()}"
        ),
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["meta"]["pagination"]["total"] == 1
    assert body["meta"]["pagination"]["page"] == 1
    assert body["meta"]["pagination"]["per_page"] == 1
    assert len(body["data"]["transactions"]) == 1
    assert body["data"]["transactions"][0]["title"] == "Freelance"


def test_transaction_list_legacy_contract_with_pagination(client) -> None:
    token = _register_and_login(client)

    create_response = client.post(
        "/transactions",
        json=_transaction_payload(title="Item legado"),
        headers=_auth_headers(token),
    )
    assert create_response.status_code == 201

    response = client.get(
        "/transactions?page=1&per_page=1",
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "success" not in body
    assert body["page"] == 1
    assert body["per_page"] == 1
    assert body["total"] >= 1
    assert len(body["transactions"]) == 1


def test_transaction_list_invalid_status_v2_contract(client) -> None:
    token = _register_and_login(client)

    response = client.get(
        "/transactions?status=invalid-status",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_list_legacy_alias_remains_available(client) -> None:
    token = _register_and_login(client)

    create_response = client.post(
        "/transactions",
        json=_transaction_payload(title="Alias legado"),
        headers=_auth_headers(token, "v2"),
    )
    assert create_response.status_code == 201

    response = client.get(
        "/transactions/list?page=1&per_page=1",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["meta"]["pagination"]["page"] == 1
    assert len(body["data"]["transactions"]) == 1


def test_transaction_detail_v2_contract(client) -> None:
    token = _register_and_login(client)

    created = client.post(
        "/transactions",
        json=_transaction_payload(title="Detalhe canônico"),
        headers=_auth_headers(token, "v2"),
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["data"]["transaction"][0]["id"]

    response = client.get(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["transaction"]["id"] == transaction_id
    assert body["data"]["transaction"]["title"] == "Detalhe canônico"


def test_transaction_detail_legacy_contract(client) -> None:
    token = _register_and_login(client)

    created = client.post(
        "/transactions",
        json=_transaction_payload(title="Detalhe legado"),
        headers=_auth_headers(token),
    )
    assert created.status_code == 201
    transaction_id = created.get_json()["transaction"][0]["id"]

    response = client.get(
        f"/transactions/{transaction_id}",
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "success" not in body
    assert body["transaction"]["id"] == transaction_id
    assert body["transaction"]["title"] == "Detalhe legado"


def test_transaction_detail_not_found_v2_contract(client) -> None:
    token = _register_and_login(client)

    response = client.get(
        f"/transactions/{uuid.uuid4()}",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 404
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_transaction_expenses_requires_period_parameter_v2_contract(client) -> None:
    token = _register_and_login(client)
    response = client.get(
        "/transactions/expenses",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_expenses_period_with_counts_and_pagination_v2_contract(
    client,
) -> None:
    token = _register_and_login(client)
    today = date.today()

    payloads = [
        _transaction_payload(
            title="Despesa antiga",
            type="expense",
            due_date=(today - timedelta(days=2)).isoformat(),
            amount="50.00",
        ),
        _transaction_payload(
            title="Receita período",
            type="income",
            due_date=today.isoformat(),
            amount="500.00",
        ),
        _transaction_payload(
            title="Despesa período A",
            type="expense",
            due_date=today.isoformat(),
            amount="120.00",
        ),
        _transaction_payload(
            title="Despesa período B",
            type="expense",
            due_date=(today + timedelta(days=1)).isoformat(),
            amount="80.00",
        ),
    ]
    for payload in payloads:
        created = client.post(
            "/transactions",
            json=payload,
            headers=_auth_headers(token, "v2"),
        )
        assert created.status_code == 201

    response = client.get(
        (
            f"/transactions/expenses?start_date={today.isoformat()}"
            f"&end_date={(today + timedelta(days=1)).isoformat()}"
            "&page=1&per_page=1&order_by=amount&order=asc"
        ),
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["meta"]["pagination"]["total"] == 2
    assert body["meta"]["pagination"]["page"] == 1
    assert body["meta"]["pagination"]["per_page"] == 1
    assert len(body["data"]["expenses"]) == 1
    assert body["data"]["expenses"][0]["title"] == "Despesa período B"
    assert body["data"]["counts"]["total_transactions"] == 3
    assert body["data"]["counts"]["income_transactions"] == 1
    assert body["data"]["counts"]["expense_transactions"] == 2
    assert response.headers["Deprecation"] == "true"
    assert (
        response.headers["X-Auraxis-Successor-Endpoint"] == "/transactions?type=expense"
    )


def test_transaction_expenses_legacy_contract(client) -> None:
    token = _register_and_login(client)
    created = client.post(
        "/transactions",
        json=_transaction_payload(type="expense", amount="100.00"),
        headers=_auth_headers(token),
    )
    assert created.status_code == 201

    response = client.get(
        f"/transactions/expenses?finalDate={date.today().isoformat()}",
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "success" not in body
    assert "expenses" in body
    assert "counts" in body
    assert "total_transactions" in body["counts"]


def test_transaction_due_range_requires_period_parameter_v2_contract(client) -> None:
    token = _register_and_login(client)

    response = client.get(
        "/transactions/due-range",
        headers=_auth_headers(token, "v2"),
    )

    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_transaction_due_range_with_unified_sorting_v2_contract(client) -> None:
    token = _register_and_login(client)
    today = date.today()
    overdue_day = (today - timedelta(days=1)).isoformat()
    upcoming_day = (today + timedelta(days=1)).isoformat()

    with client.application.app_context():
        user_id = UUID(decode_token(token)["sub"])
        card_a = CreditCard(user_id=user_id, name="Cartao A")
        card_b = CreditCard(user_id=user_id, name="Cartao B")
        db.session.add_all([card_a, card_b])
        db.session.commit()
        card_a_id = str(card_a.id)
        card_b_id = str(card_b.id)

    payloads = [
        _transaction_payload(
            title="Receita vencida",
            type="income",
            due_date=overdue_day,
            amount="200.00",
            credit_card_id=card_b_id,
        ),
        _transaction_payload(
            title="Conta mensal",
            type="expense",
            due_date=upcoming_day,
            amount="80.00",
            credit_card_id=card_b_id,
        ),
        _transaction_payload(
            title="Conta mensal",
            type="expense",
            due_date=upcoming_day,
            amount="60.00",
            credit_card_id=card_a_id,
        ),
    ]
    for payload in payloads:
        created = client.post(
            "/transactions",
            json=payload,
            headers=_auth_headers(token, "v2"),
        )
        assert created.status_code == 201

    upcoming_first_response = client.get(
        (
            f"/transactions/due-range?start_date={overdue_day}"
            f"&end_date={upcoming_day}&order_by=upcoming_first&page=1&per_page=10"
        ),
        headers=_auth_headers(token, "v2"),
    )
    assert upcoming_first_response.status_code == 200
    upcoming_body = upcoming_first_response.get_json()
    assert upcoming_body["success"] is True
    assert upcoming_body["meta"]["pagination"]["total"] == 3
    assert upcoming_body["data"]["counts"]["total_transactions"] == 3
    assert upcoming_body["data"]["counts"]["income_transactions"] == 1
    assert upcoming_body["data"]["counts"]["expense_transactions"] == 2
    assert upcoming_body["data"]["transactions"][0]["credit_card_id"] == card_a_id

    overdue_first_response = client.get(
        (
            f"/transactions/due-range?start_date={overdue_day}"
            f"&end_date={upcoming_day}&order_by=overdue_first&page=1&per_page=10"
        ),
        headers=_auth_headers(token, "v2"),
    )
    assert overdue_first_response.status_code == 200
    overdue_body = overdue_first_response.get_json()
    assert overdue_body["success"] is True
    assert overdue_body["data"]["transactions"][0]["title"] == "Receita vencida"


def test_transaction_due_range_legacy_contract(client) -> None:
    token = _register_and_login(client)
    created = client.post(
        "/transactions",
        json=_transaction_payload(type="expense", amount="100.00"),
        headers=_auth_headers(token),
    )
    assert created.status_code == 201

    response = client.get(
        f"/transactions/due-range?finalDate={date.today().isoformat()}",
        headers=_auth_headers(token),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert "success" not in body
    assert "transactions" in body
    assert "counts" in body
    assert "total_transactions" in body["counts"]
