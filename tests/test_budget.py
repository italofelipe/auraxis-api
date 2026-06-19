"""Integration tests for Budget feature — CRUD, spent calculation, summary."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any  # noqa: UP006

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _register_and_login(client, *, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"

    reg = client.post(
        "/auth/register",
        json={"name": f"user-{suffix}", "email": email, "password": password},
    )
    assert reg.status_code == 201, reg.get_json()

    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.get_json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


def _budget_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": "Alimentação Mensal",
        "amount": "800.00",
        "period": "monthly",
    }
    payload.update(overrides)
    return payload


def _create_tag(client, token: str, name: str = "Alimentação") -> str:
    """Creates a tag and returns its ID."""
    resp = client.post(
        "/tags",
        json={"name": name, "color": "#FF6B6B", "icon": "🍔"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    # Try common response shapes
    if "data" in body and "tag" in body["data"]:
        return body["data"]["tag"]["id"]
    if "tag" in body:
        return body["tag"]["id"]
    if "id" in body:
        return body["id"]
    raise AssertionError(f"Cannot extract tag id from: {body}")


def _create_paid_expense(
    client,
    token: str,
    *,
    amount: str,
    title: str,
    impact_policy: str = "full",
) -> None:
    resp = client.post(
        "/transactions",
        json={
            "title": title,
            "amount": amount,
            "type": "expense",
            "status": "paid",
            "due_date": date.today().isoformat(),
            "impact_policy": impact_policy,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_json()


# ---------------------------------------------------------------------------
# CRUD tests
# ---------------------------------------------------------------------------


def test_budget_create_and_list(client) -> None:
    token = _register_and_login(client, prefix="budget-crud")

    # Create
    resp = client.post("/budgets", json=_budget_payload(), headers=_auth(token))
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["success"] is True
    budget = body["data"]["budget"]
    assert budget["name"] == "Alimentação Mensal"
    assert budget["period"] == "monthly"
    assert budget["is_active"] is True
    assert "spent" in budget
    assert "remaining" in budget
    assert "percentage_used" in budget
    assert "is_over_budget" in budget

    # List
    list_resp = client.get("/budgets", headers=_auth(token))
    assert list_resp.status_code == 200
    list_body = list_resp.get_json()
    assert list_body["success"] is True
    items = list_body["data"]["items"]
    assert len(items) >= 1
    assert any(b["name"] == "Alimentação Mensal" for b in items)


def test_budget_get_detail(client) -> None:
    token = _register_and_login(client, prefix="budget-detail")

    create_resp = client.post("/budgets", json=_budget_payload(), headers=_auth(token))
    assert create_resp.status_code == 201
    budget_id = create_resp.get_json()["data"]["budget"]["id"]

    get_resp = client.get(f"/budgets/{budget_id}", headers=_auth(token))
    assert get_resp.status_code == 200
    get_body = get_resp.get_json()
    assert get_body["success"] is True
    assert get_body["data"]["budget"]["id"] == budget_id


def test_budget_update(client) -> None:
    token = _register_and_login(client, prefix="budget-update")

    create_resp = client.post("/budgets", json=_budget_payload(), headers=_auth(token))
    assert create_resp.status_code == 201
    budget_id = create_resp.get_json()["data"]["budget"]["id"]

    patch_resp = client.patch(
        f"/budgets/{budget_id}",
        json={"name": "Alimentação Atualizada", "amount": "1000.00"},
        headers=_auth(token),
    )
    assert patch_resp.status_code == 200
    patch_body = patch_resp.get_json()
    assert patch_body["success"] is True
    assert patch_body["data"]["budget"]["name"] == "Alimentação Atualizada"
    assert patch_body["data"]["budget"]["amount"] == "1000.00"


def test_budget_delete(client) -> None:
    token = _register_and_login(client, prefix="budget-delete")

    create_resp = client.post("/budgets", json=_budget_payload(), headers=_auth(token))
    assert create_resp.status_code == 201
    budget_id = create_resp.get_json()["data"]["budget"]["id"]

    del_resp = client.delete(f"/budgets/{budget_id}", headers=_auth(token))
    assert del_resp.status_code == 200
    assert del_resp.get_json()["success"] is True

    # Budget is gone
    get_resp = client.get(f"/budgets/{budget_id}", headers=_auth(token))
    assert get_resp.status_code == 404


# ---------------------------------------------------------------------------
# Spent calculation — monthly period
# ---------------------------------------------------------------------------


def test_budget_spent_calculation_monthly(client) -> None:
    """Spent is 0 when no transactions exist."""
    token = _register_and_login(client, prefix="budget-spent")

    create_resp = client.post(
        "/budgets",
        json=_budget_payload(amount="500.00"),
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    budget = create_resp.get_json()["data"]["budget"]

    # No transactions yet → spent should be 0
    assert float(budget["spent"]) == 0.0
    assert float(budget["remaining"]) == 500.0
    assert budget["percentage_used"] == 0.0
    assert budget["is_over_budget"] is False


def test_budget_spent_uses_committed_monthly_expenses_for_tag_envelope(
    client, app
) -> None:
    """Monthly envelope usage counts paid, pending and overdue expenses only."""
    token = _register_and_login(client, prefix="budget-committed")
    tag_id = _create_tag(client, token, name="Streaming")
    other_tag_id = _create_tag(client, token, name="Mercado")

    create_resp = client.post(
        "/budgets",
        json=_budget_payload(name="Streaming", amount="500.00", tag_id=tag_id),
        headers=_auth(token),
    )
    assert create_resp.status_code == 201
    budget_id = create_resp.get_json()["data"]["budget"]["id"]

    from flask_jwt_extended import decode_token

    from app.extensions.database import db
    from app.models.transaction import Transaction, TransactionStatus, TransactionType

    user_id = uuid.UUID(decode_token(token)["sub"])
    current_month_day = date.today().replace(day=10)
    previous_month_day = current_month_day.replace(day=1) - timedelta(days=1)

    with app.app_context():
        db.session.add_all(
            [
                Transaction(
                    user_id=user_id,
                    title="Netflix pago",
                    amount=Decimal("50.00"),
                    type=TransactionType.EXPENSE,
                    status=TransactionStatus.PAID,
                    due_date=current_month_day,
                    tag_id=uuid.UUID(tag_id),
                ),
                Transaction(
                    user_id=user_id,
                    title="Prime pendente",
                    amount=Decimal("70.00"),
                    type=TransactionType.EXPENSE,
                    status=TransactionStatus.PENDING,
                    due_date=current_month_day,
                    tag_id=uuid.UUID(tag_id),
                ),
                Transaction(
                    user_id=user_id,
                    title="Spotify vencido",
                    amount=Decimal("30.00"),
                    type=TransactionType.EXPENSE,
                    status=TransactionStatus.OVERDUE,
                    due_date=current_month_day,
                    tag_id=uuid.UUID(tag_id),
                ),
                Transaction(
                    user_id=user_id,
                    title="Assinatura cancelada",
                    amount=Decimal("90.00"),
                    type=TransactionType.EXPENSE,
                    status=TransactionStatus.CANCELLED,
                    due_date=current_month_day,
                    tag_id=uuid.UUID(tag_id),
                ),
                Transaction(
                    user_id=user_id,
                    title="Assinatura postergada",
                    amount=Decimal("60.00"),
                    type=TransactionType.EXPENSE,
                    status=TransactionStatus.POSTPONED,
                    due_date=current_month_day,
                    tag_id=uuid.UUID(tag_id),
                ),
                Transaction(
                    user_id=user_id,
                    title="Reembolso streaming",
                    amount=Decimal("200.00"),
                    type=TransactionType.INCOME,
                    status=TransactionStatus.PAID,
                    due_date=current_month_day,
                    tag_id=uuid.UUID(tag_id),
                ),
                Transaction(
                    user_id=user_id,
                    title="Despesa deletada",
                    amount=Decimal("40.00"),
                    type=TransactionType.EXPENSE,
                    status=TransactionStatus.PAID,
                    due_date=current_month_day,
                    tag_id=uuid.UUID(tag_id),
                    deleted=True,
                ),
                Transaction(
                    user_id=user_id,
                    title="Outro envelope",
                    amount=Decimal("20.00"),
                    type=TransactionType.EXPENSE,
                    status=TransactionStatus.PENDING,
                    due_date=current_month_day,
                    tag_id=uuid.UUID(other_tag_id),
                ),
                Transaction(
                    user_id=user_id,
                    title="Streaming mês anterior",
                    amount=Decimal("100.00"),
                    type=TransactionType.EXPENSE,
                    status=TransactionStatus.PAID,
                    due_date=previous_month_day,
                    tag_id=uuid.UUID(tag_id),
                ),
            ],
        )
        db.session.commit()

    detail_resp = client.get(f"/budgets/{budget_id}", headers=_auth(token))
    assert detail_resp.status_code == 200
    budget = detail_resp.get_json()["data"]["budget"]
    assert Decimal(budget["spent"]) == Decimal("150.00")
    assert Decimal(budget["remaining"]) == Decimal("350.00")
    assert budget["percentage_used"] == 30.0
    assert budget["is_over_budget"] is False


# ---------------------------------------------------------------------------
# Budget with no tag (overall budget)
# ---------------------------------------------------------------------------


def test_budget_with_no_tag(client) -> None:
    token = _register_and_login(client, prefix="budget-notag")

    resp = client.post(
        "/budgets",
        json=_budget_payload(name="Geral Mensal"),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    budget = resp.get_json()["data"]["budget"]
    assert budget["tag_id"] is None
    assert budget["tag_name"] is None
    assert budget["tag_color"] is None


# ---------------------------------------------------------------------------
# Budget with tag association
# ---------------------------------------------------------------------------


def test_budget_with_tag(client) -> None:
    token = _register_and_login(client, prefix="budget-tag")

    # Some APIs return tags from a seeded list; try to get one first
    tags_resp = client.get("/tags", headers=_auth(token))
    if tags_resp.status_code == 200:
        tags_data = tags_resp.get_json()
        # Handle different response shapes
        if isinstance(tags_data, list) and len(tags_data) > 0:
            tag_id = tags_data[0]["id"]
        elif (
            isinstance(tags_data, dict)
            and "data" in tags_data
            and isinstance(tags_data["data"], list)
            and len(tags_data["data"]) > 0
        ):
            tag_id = tags_data["data"][0]["id"]
        else:
            tag_id = _create_tag(client, token)
    else:
        tag_id = _create_tag(client, token)

    resp = client.post(
        "/budgets",
        json=_budget_payload(tag_id=tag_id),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    budget = resp.get_json()["data"]["budget"]
    assert budget["tag_id"] == tag_id
    assert budget["tag_name"] is not None


# ---------------------------------------------------------------------------
# Over-budget detection
# ---------------------------------------------------------------------------


def test_over_budget_flag_on_zero_amount_edge(client) -> None:
    """is_over_budget is False when spent == 0 and amount > 0."""
    token = _register_and_login(client, prefix="budget-over")

    resp = client.post(
        "/budgets",
        json=_budget_payload(amount="100.00"),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    budget = resp.get_json()["data"]["budget"]
    assert budget["is_over_budget"] is False


# ---------------------------------------------------------------------------
# Summary endpoint
# ---------------------------------------------------------------------------


def test_budget_summary_endpoint(client) -> None:
    token = _register_and_login(client, prefix="budget-summary")

    # Create two budgets
    client.post("/budgets", json=_budget_payload(amount="500.00"), headers=_auth(token))
    client.post(
        "/budgets",
        json=_budget_payload(name="Transporte", amount="300.00"),
        headers=_auth(token),
    )

    resp = client.get("/budgets/summary", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    summary = body["data"]["summary"]
    assert "total_budgeted" in summary
    assert "total_spent" in summary
    assert "total_remaining" in summary
    assert "percentage_used" in summary
    assert "budget_count" in summary
    assert summary["budget_count"] == 2
    assert summary["total_budgeted"] == "800.00"


def test_budget_spent_ignores_cards_only_impact_policy(client) -> None:
    token = _register_and_login(client, prefix="budget-impact-policy")

    create_resp = client.post(
        "/budgets",
        json=_budget_payload(name="Geral Mensal", amount="500.00"),
        headers=_auth(token),
    )
    assert create_resp.status_code == 201

    _create_paid_expense(
        client,
        token,
        title="Mercado",
        amount="120.00",
        impact_policy="full",
    )
    _create_paid_expense(
        client,
        token,
        title="Compra só no cartão",
        amount="80.00",
        impact_policy="cards_only",
    )

    summary_resp = client.get("/budgets/summary", headers=_auth(token))
    assert summary_resp.status_code == 200
    summary = summary_resp.get_json()["data"]["summary"]
    assert summary["total_spent"] == "120.00"
    assert summary["total_remaining"] == "380.00"


# ---------------------------------------------------------------------------
# Forbidden — non-owner cannot access
# ---------------------------------------------------------------------------


def test_budget_forbidden_for_non_owner(client) -> None:
    owner_token = _register_and_login(client, prefix="budget-owner")
    other_token = _register_and_login(client, prefix="budget-other")

    create_resp = client.post(
        "/budgets", json=_budget_payload(), headers=_auth(owner_token)
    )
    assert create_resp.status_code == 201
    budget_id = create_resp.get_json()["data"]["budget"]["id"]

    # Other user cannot access
    resp = client.get(f"/budgets/{budget_id}", headers=_auth(other_token))
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_budget_invalid_period_returns_validation_error(client) -> None:
    token = _register_and_login(client, prefix="budget-valperiod")

    resp = client.post(
        "/budgets",
        json=_budget_payload(period="yearly"),
        headers=_auth(token),
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_budget_missing_name_returns_validation_error(client) -> None:
    token = _register_and_login(client, prefix="budget-valname")

    payload = {"amount": "500.00", "period": "monthly"}
    resp = client.post("/budgets", json=payload, headers=_auth(token))
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_budget_custom_period(client) -> None:
    token = _register_and_login(client, prefix="budget-custom")

    resp = client.post(
        "/budgets",
        json=_budget_payload(
            period="custom",
            start_date="2026-04-01",
            end_date="2026-04-30",
        ),
        headers=_auth(token),
    )
    assert resp.status_code == 201
    budget = resp.get_json()["data"]["budget"]
    assert budget["period"] == "custom"
    assert budget["start_date"] == "2026-04-01"
    assert budget["end_date"] == "2026-04-30"
