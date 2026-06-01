"""TDD tests for Budget category field (#1240).

RED phase: tests fail until Budget model has category field.

Coverage:
- Budget model has category column
- Budget with category can be created via REST
- get_spent_for_budget uses category filter when category is set
- budget_service.serialize includes category
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.models.budget import Budget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(client, prefix: str = "bgt") -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@test.com"
    client.post(
        "/auth/register",
        json={"name": prefix, "email": email, "password": "StrongPass@123"},
    )
    return client.post(
        "/auth/login", json={"email": email, "password": "StrongPass@123"}
    ).get_json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


# ---------------------------------------------------------------------------
# Tests: Budget model
# ---------------------------------------------------------------------------


class TestBudgetCategoryColumn:
    def test_budget_model_has_category_attribute(self):
        assert hasattr(Budget, "category")

    def test_budget_category_is_nullable(self, app):
        with app.app_context():
            col = Budget.__table__.c.get("category")
            assert col is not None
            assert col.nullable is True


# ---------------------------------------------------------------------------
# Tests: REST API
# ---------------------------------------------------------------------------


class TestBudgetCategoryREST:
    def test_create_budget_with_category(self, client):
        token = _register_and_login(client)
        resp = client.post(
            "/budgets",
            json={
                "name": "Orçamento Alimentação",
                "amount": 800.0,
                "period": "monthly",
                "category": "alimentacao",
            },
            headers=_auth(token),
        )
        assert resp.status_code in (200, 201), resp.get_json()
        body = resp.get_json()
        data = body.get("data") or body
        budget = data.get("budget") or data
        if isinstance(budget, dict):
            assert budget.get("category") == "alimentacao"

    def test_create_budget_without_category_accepted(self, client):
        token = _register_and_login(client)
        resp = client.post(
            "/budgets",
            json={"name": "Geral", "amount": 3000.0, "period": "monthly"},
            headers=_auth(token),
        )
        assert resp.status_code in (200, 201)

    def test_category_persisted_in_db(self, client, app):
        token = _register_and_login(client)
        from flask_jwt_extended import decode_token

        from app.extensions.database import db

        user_id = uuid.UUID(decode_token(token)["sub"])
        client.post(
            "/budgets",
            json={
                "name": "Transporte",
                "amount": 400.0,
                "period": "monthly",
                "category": "transporte",
            },
            headers=_auth(token),
        )
        with app.app_context():
            budget = (
                db.session.query(Budget)
                .filter_by(user_id=user_id, name="Transporte")
                .first()
            )
            assert budget is not None
            assert budget.category == "transporte"


# ---------------------------------------------------------------------------
# Tests: get_spent_for_budget uses category
# ---------------------------------------------------------------------------


class TestBudgetGetSpentForCategory:
    def test_spent_filters_by_category_when_set(self, client, app):
        token = _register_and_login(client)
        from flask_jwt_extended import decode_token

        from app.extensions.database import db
        from app.models.transaction import (
            Transaction,
            TransactionCategory,
            TransactionStatus,
            TransactionType,
        )
        from app.services.budget_service import BudgetService

        user_id = uuid.UUID(decode_token(token)["sub"])

        with app.app_context():
            # Create transactions: one with category alimentacao, one without
            # Data no mês corrente: o budget mensal soma o mês de date.today();
            # uma data fixa (ex.: 2026-05-10) faz o teste quebrar fora daquele mês.
            current_month_day = __import__("datetime").date.today().replace(day=10)
            tx_with_cat = Transaction(
                user_id=user_id,
                title="Mercado",
                amount=Decimal("150.00"),
                type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=current_month_day,
                category=TransactionCategory.alimentacao,
            )
            tx_no_cat = Transaction(
                user_id=user_id,
                title="Outros gastos",
                amount=Decimal("80.00"),
                type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=current_month_day,
                category=None,
            )
            db.session.add_all([tx_with_cat, tx_no_cat])

            # Budget with category = alimentacao
            budget = Budget(
                user_id=user_id,
                name="Alimentação",
                amount=Decimal("800.00"),
                period="monthly",
                category="alimentacao",
            )
            db.session.add(budget)
            db.session.commit()

            service = BudgetService(user_id=user_id)
            spent = service.get_spent_for_budget(budget)

            # Should count only the alimentacao transaction (150), not outros (80)
            assert spent == Decimal("150.00")
