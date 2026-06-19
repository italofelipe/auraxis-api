"""Live PostgreSQL verification for credit-card impact policy flows.

This file is opt-in because it requires a real migrated PostgreSQL database.
Run through `scripts/test_credit_card_impact_policy_live_db.sh` for an
ephemeral Docker database.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Any, Generator
from uuid import uuid4

import pytest

from app.extensions.database import db
from app.services.credit_card_bill_service import compute_bill_cycle
from tests.conftest import TEST_ENV_OVERRIDES

pytestmark = pytest.mark.live_db


@pytest.fixture
def live_client() -> Generator[Any, None, None]:
    database_url = os.getenv("AURAXIS_LIVE_DATABASE_URL")
    if not database_url:
        pytest.skip("Set AURAXIS_LIVE_DATABASE_URL to run live DB tests.")

    os.environ["DATABASE_URL"] = database_url
    for key, value in TEST_ENV_OVERRIDES.items():
        os.environ[key] = value

    from app import create_app

    app = create_app(enable_http_runtime=False)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client

    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _register_and_login(client: Any) -> str:
    suffix = uuid4().hex
    email = f"credit-card-live-{suffix}@example.com"
    password = "StrongPass@123"

    register = client.post(
        "/auth/register",
        json={"name": f"Live {suffix[:8]}", "email": email, "password": password},
    )
    assert register.status_code == 201, register.get_json()

    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.get_json()
    return str(login.get_json()["token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


def _create_card(client: Any, token: str, *, name: str) -> str:
    response = client.post(
        "/credit-cards",
        json={
            "name": name,
            "brand": "visa",
            "bank": "Banco Live",
            "limit_amount": "2000.00",
            "closing_day": 28,
            "due_day": 5,
        },
        headers=_auth(token),
    )
    assert response.status_code == 201, response.get_json()
    return str(response.get_json()["data"]["credit_card"]["id"])


def _create_transaction(
    client: Any,
    token: str,
    *,
    card_id: str,
    title: str,
    amount: str,
    impact_policy: str,
    purchase_date: date,
) -> str:
    response = client.post(
        "/transactions",
        json={
            "title": title,
            "amount": amount,
            "type": "expense",
            "status": "paid",
            "due_date": purchase_date.isoformat(),
            "credit_card_id": card_id,
            "impact_policy": impact_policy,
        },
        headers=_auth(token),
    )
    assert response.status_code == 201, response.get_json()
    return str(response.get_json()["data"]["transaction"][0]["id"])


def test_credit_card_impact_policy_live_postgres_flow(live_client: Any) -> None:
    token = _register_and_login(live_client)
    headers = _auth(token)
    today = date.today()
    cycle = compute_bill_cycle(closing_day=28, due_day=5, anchor=today)

    card_id = _create_card(live_client, token, name="Cartao live principal")
    other_card_id = _create_card(live_client, token, name="Cartao live secundario")

    budget = live_client.post(
        "/budgets",
        json={"name": "Budget live geral", "amount": "100.00", "period": "monthly"},
        headers=headers,
    )
    assert budget.status_code == 201, budget.get_json()
    budget_id = budget.get_json()["data"]["budget"]["id"]

    full_transaction_id = _create_transaction(
        live_client,
        token,
        card_id=card_id,
        title="Compra full no cartão",
        amount="25.00",
        impact_policy="full",
        purchase_date=today,
    )
    cards_only_transaction_id = _create_transaction(
        live_client,
        token,
        card_id=card_id,
        title="Compra apenas cartão",
        amount="40.00",
        impact_policy="cards_only",
        purchase_date=today,
    )
    _create_transaction(
        live_client,
        token,
        card_id=other_card_id,
        title="Compra em outro cartão",
        amount="15.00",
        impact_policy="full",
        purchase_date=today,
    )

    budget_response = live_client.get(f"/budgets/{budget_id}", headers=headers)
    assert budget_response.status_code == 200, budget_response.get_json()
    budget_payload = budget_response.get_json()["data"]["budget"]
    assert Decimal(budget_payload["spent"]) == Decimal("40.00")

    bill_response = live_client.get(
        f"/credit-cards/{card_id}/bill?month={cycle.end_date:%Y-%m}",
        headers=headers,
    )
    assert bill_response.status_code == 200, bill_response.get_json()
    bill_payload = bill_response.get_json()["data"]
    bill_ids = {item["id"] for item in bill_payload["transactions"]}
    assert full_transaction_id in bill_ids
    assert cards_only_transaction_id in bill_ids
    assert Decimal(bill_payload["total_amount"]) == Decimal("65.00")

    list_response = live_client.get(
        f"/transactions?credit_card_id={card_id}&per_page=50",
        headers=headers,
    )
    assert list_response.status_code == 200, list_response.get_json()
    listed_ids = {
        item["id"] for item in list_response.get_json()["data"]["transactions"]
    }
    assert full_transaction_id in listed_ids
    assert cards_only_transaction_id in listed_ids
    assert len(listed_ids) == 2
