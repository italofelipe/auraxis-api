"""Integration tests: active-transactions listing follows the bill cycle.

Reproduces the bug where a credit-card purchase made right after the card's
closing day was listed under the calendar month of its ``due_date`` instead of
the month of the bill it belongs to. After the fix, when the listing is scoped
to a full calendar month, credit-card transactions are grouped by their bill
cycle while non-card transactions and incomes stay on the calendar month.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from app.extensions.database import db
from app.models.transaction import Transaction, TransactionStatus, TransactionType


def _register_and_login(client, *, prefix: str) -> str:
    from uuid import uuid4

    suffix = uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"
    register = client.post(
        "/auth/register",
        json={"name": f"user-{suffix}", "email": email, "password": password},
    )
    assert register.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.get_json()["token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


def _user_id_from_token(app, token: str) -> str:
    from flask_jwt_extended import decode_token

    with app.app_context():
        return str(decode_token(token)["sub"])


def _create_card(client, headers, *, closing_day: int, due_day: int) -> dict:
    payload = {
        "name": "Nubank",
        "brand": "mastercard",
        "limit_amount": 5000.0,
        "closing_day": closing_day,
        "due_day": due_day,
    }
    response = client.post("/credit-cards", json=payload, headers=headers)
    assert response.status_code == 201
    return response.get_json()["data"]["credit_card"]


def _insert_tx(
    app,
    *,
    user_id: str,
    due_date: date,
    title: str,
    card_id: str | None = None,
    tx_type: TransactionType = TransactionType.EXPENSE,
) -> None:
    with app.app_context():
        tx = Transaction(
            user_id=UUID(user_id),
            credit_card_id=UUID(card_id) if card_id else None,
            title=title,
            amount=Decimal("100.00"),
            due_date=due_date,
            status=TransactionStatus.PENDING,
            type=tx_type,
        )
        db.session.add(tx)
        db.session.commit()


def _list_titles(client, headers, *, start_date: str, end_date: str) -> set[str]:
    response = client.get(
        f"/transactions?start_date={start_date}&end_date={end_date}&per_page=100",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.get_json()
    items = body["data"]["transactions"]
    return {item["title"] for item in items}


class TestActiveListingFollowsBillCycle:
    """Card purchases after closing day move to the next month's listing."""

    def test_card_purchase_after_closing_appears_in_following_month(
        self, app, client
    ) -> None:
        token = _register_and_login(client, prefix="comp-list")
        headers = _auth_headers(token)
        user_id = _user_id_from_token(app, token)
        # Closes on the 10th. July cycle is 2026-06-11 .. 2026-07-10, so a
        # purchase on 2026-06-19 belongs to July's bill.
        card = _create_card(client, headers, closing_day=10, due_day=15)
        _insert_tx(
            app,
            user_id=user_id,
            card_id=card["id"],
            due_date=date(2026, 6, 19),
            title="card-jun19",
        )

        # (1) July listing INCLUDES the June-19 card purchase.
        july = _list_titles(
            client, headers, start_date="2026-07-01", end_date="2026-07-31"
        )
        assert "card-jun19" in july

        # (2) June listing EXCLUDES it (it belongs to July's bill).
        june = _list_titles(
            client, headers, start_date="2026-06-01", end_date="2026-06-30"
        )
        assert "card-jun19" not in june

    def test_income_and_non_card_stay_on_calendar_month(self, app, client) -> None:
        token = _register_and_login(client, prefix="comp-cal")
        headers = _auth_headers(token)
        user_id = _user_id_from_token(app, token)
        _create_card(client, headers, closing_day=10, due_day=15)
        _insert_tx(
            app,
            user_id=user_id,
            due_date=date(2026, 7, 5),
            title="salary-jul",
            tx_type=TransactionType.INCOME,
        )
        _insert_tx(app, user_id=user_id, due_date=date(2026, 6, 30), title="rent-jun")

        july = _list_titles(
            client, headers, start_date="2026-07-01", end_date="2026-07-31"
        )
        assert "salary-jul" in july
        assert "rent-jun" not in july

    def test_custom_partial_range_keeps_raw_due_date_filter(self, app, client) -> None:
        token = _register_and_login(client, prefix="comp-range")
        headers = _auth_headers(token)
        user_id = _user_id_from_token(app, token)
        card = _create_card(client, headers, closing_day=10, due_day=15)
        # Card purchase on June 19 belongs to July's bill, but a custom partial
        # range must behave like a raw due_date filter (no competence remap).
        _insert_tx(
            app,
            user_id=user_id,
            card_id=card["id"],
            due_date=date(2026, 6, 19),
            title="card-jun19",
        )

        # Range 2026-06-01..2026-06-30 is a full month → competence applies →
        # excluded. But a partial range that contains June 19 must include it.
        partial = _list_titles(
            client, headers, start_date="2026-06-15", end_date="2026-06-20"
        )
        assert "card-jun19" in partial

    def test_pagination_total_matches_competence_filter(self, app, client) -> None:
        # The total/count must agree with the competence-filtered items so the
        # paginator stays consistent.
        token = _register_and_login(client, prefix="comp-count")
        headers = _auth_headers(token)
        user_id = _user_id_from_token(app, token)
        card = _create_card(client, headers, closing_day=10, due_day=15)
        _insert_tx(
            app,
            user_id=user_id,
            card_id=card["id"],
            due_date=date(2026, 6, 19),
            title="card-jun19",
        )
        _insert_tx(
            app,
            user_id=user_id,
            card_id=card["id"],
            due_date=date(2026, 7, 20),
            title="card-jul20",
        )

        response = client.get(
            "/transactions?start_date=2026-07-01&end_date=2026-07-31&per_page=100",
            headers=headers,
        )
        assert response.status_code == 200
        body = response.get_json()
        titles = {item["title"] for item in body["data"]["transactions"]}
        assert titles == {"card-jun19"}
        assert body["meta"]["pagination"]["total"] == 1
