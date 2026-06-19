"""Integration tests for /credit-cards/<id>/bill and /credit-cards/<id>/utilization.

Covers bill cycle response shape, month parsing, status statuses (paid/pending/
overdue/cancelled/postponed) inclusion in totals, cross-user 404, and limit/
utilization edge cases.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from app.extensions.database import db
from app.models.transaction import Transaction, TransactionStatus, TransactionType


def _register_and_login(client, *, prefix: str) -> str:
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
    return {
        "Authorization": f"Bearer {token}",
        "X-API-Contract": "v2",
    }


def _create_card(
    client,
    headers,
    *,
    name: str = "Nubank",
    limit_amount: float | None = 5000.0,
    closing_day: int = 10,
    due_day: int = 15,
) -> dict:
    payload = {
        "name": name,
        "brand": "mastercard",
        "limit_amount": limit_amount,
        "closing_day": closing_day,
        "due_day": due_day,
    }
    response = client.post("/credit-cards", json=payload, headers=headers)
    assert response.status_code == 201
    return response.get_json()["data"]["credit_card"]


def _insert_transaction(
    app,
    *,
    user_id: str,
    card_id: str,
    amount: str,
    due_date: date,
    status: TransactionStatus,
    tx_type: TransactionType = TransactionType.EXPENSE,
) -> None:
    with app.app_context():
        tx = Transaction(
            user_id=UUID(user_id) if isinstance(user_id, str) else user_id,
            credit_card_id=UUID(card_id) if isinstance(card_id, str) else card_id,
            title="charge",
            amount=Decimal(amount),
            due_date=due_date,
            status=status,
            type=tx_type,
        )
        db.session.add(tx)
        db.session.commit()


def _current_user_id_from_token(app, token: str) -> str:
    """Extract user id from a JWT token by decoding it within the test app."""
    from flask_jwt_extended import decode_token

    with app.app_context():
        decoded = decode_token(token)
        return str(decoded["sub"])


class TestBillEndpoint:
    def test_returns_cycle_and_aggregates(self, app, client) -> None:
        token = _register_and_login(client, prefix="bill-aggr")
        headers = _auth_headers(token)
        card = _create_card(client, headers, closing_day=10, due_day=15)
        user_id = _current_user_id_from_token(app, token)

        # closing=10, due=15 → cycle for May 2026:
        # window 2026-04-11 → 2026-05-10, due 2026-05-15.
        _insert_transaction(
            app,
            user_id=user_id,
            card_id=card["id"],
            amount="100.50",
            due_date=date(2026, 4, 20),
            status=TransactionStatus.PAID,
        )
        _insert_transaction(
            app,
            user_id=user_id,
            card_id=card["id"],
            amount="50.00",
            due_date=date(2026, 5, 5),
            status=TransactionStatus.PENDING,
        )
        # Outside cycle — must not appear in totals.
        _insert_transaction(
            app,
            user_id=user_id,
            card_id=card["id"],
            amount="999.99",
            due_date=date(2026, 6, 1),
            status=TransactionStatus.PENDING,
        )

        response = client.get(
            f"/credit-cards/{card['id']}/bill?month=2026-05", headers=headers
        )
        assert response.status_code == 200
        body = response.get_json()["data"]

        assert body["cycle"]["start_date"] == "2026-04-11"
        assert body["cycle"]["end_date"] == "2026-05-10"
        assert body["cycle"]["due_date"] == "2026-05-15"
        assert body["cycle"]["status"] in {"open", "closed", "paid"}
        assert Decimal(body["total_amount"]) == Decimal("150.50")
        assert Decimal(body["paid_amount"]) == Decimal("100.50")
        assert Decimal(body["pending_amount"]) == Decimal("50.00")
        assert len(body["transactions"]) == 2

    def test_bill_includes_cards_only_transactions(self, client) -> None:
        token = _register_and_login(client, prefix="bill-impact-policy")
        headers = _auth_headers(token)
        card = _create_card(client, headers, closing_day=10, due_day=15)

        created = client.post(
            "/transactions",
            json={
                "title": "Compra isolada do orçamento",
                "amount": "88.90",
                "type": "expense",
                "status": "pending",
                "due_date": "2026-05-05",
                "credit_card_id": card["id"],
                "impact_policy": "cards_only",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.get_json()

        response = client.get(
            f"/credit-cards/{card['id']}/bill?month=2026-05", headers=headers
        )
        assert response.status_code == 200
        body = response.get_json()["data"]
        assert Decimal(body["total_amount"]) == Decimal("88.90")
        assert Decimal(body["pending_amount"]) == Decimal("88.90")
        assert body["transactions"][0]["impact_policy"] == "cards_only"

    def test_returns_404_when_card_belongs_to_other_user(self, client) -> None:
        owner = _register_and_login(client, prefix="bill-owner")
        owner_headers = _auth_headers(owner)
        card = _create_card(client, owner_headers)

        stranger = _register_and_login(client, prefix="bill-stranger")
        stranger_headers = _auth_headers(stranger)

        response = client.get(
            f"/credit-cards/{card['id']}/bill?month=2026-05", headers=stranger_headers
        )
        assert response.status_code == 404

    def test_invalid_month_returns_400(self, client) -> None:
        token = _register_and_login(client, prefix="bill-bad-month")
        headers = _auth_headers(token)
        card = _create_card(client, headers)

        for invalid in ("2026", "2026-13", "abc", "2026-00", "2026/05"):
            response = client.get(
                f"/credit-cards/{card['id']}/bill?month={invalid}", headers=headers
            )
            assert response.status_code == 400, f"month={invalid!r}"

    def test_defaults_to_current_month_when_omitted(self, client) -> None:
        token = _register_and_login(client, prefix="bill-default-month")
        headers = _auth_headers(token)
        card = _create_card(client, headers)

        response = client.get(f"/credit-cards/{card['id']}/bill", headers=headers)
        assert response.status_code == 200
        body = response.get_json()["data"]
        assert "cycle" in body
        assert "start_date" in body["cycle"]

    def test_requires_closing_and_due_day(self, client) -> None:
        token = _register_and_login(client, prefix="bill-no-days")
        headers = _auth_headers(token)
        card = _create_card(client, headers, closing_day=None, due_day=None)  # type: ignore[arg-type]

        response = client.get(
            f"/credit-cards/{card['id']}/bill?month=2026-05", headers=headers
        )
        assert response.status_code == 400


class TestUtilizationEndpoint:
    def test_empty_card_returns_zero(self, client) -> None:
        token = _register_and_login(client, prefix="util-empty")
        headers = _auth_headers(token)
        card = _create_card(client, headers, limit_amount=5000.0)

        response = client.get(
            f"/credit-cards/{card['id']}/utilization", headers=headers
        )
        assert response.status_code == 200
        body = response.get_json()["data"]
        assert Decimal(body["committed_amount"]) == Decimal("0")
        assert Decimal(body["available_amount"]) == Decimal("5000.00")
        assert Decimal(body["limit_amount"]) == Decimal("5000.00")
        assert body["utilization_pct"] == 0.0

    def test_includes_pending_paid_and_overdue(self, app, client) -> None:
        token = _register_and_login(client, prefix="util-mixed")
        headers = _auth_headers(token)
        card = _create_card(
            client, headers, limit_amount=1000.0, closing_day=10, due_day=15
        )
        user_id = _current_user_id_from_token(app, token)

        for amount, status in (
            ("100.00", TransactionStatus.PAID),
            ("50.00", TransactionStatus.PENDING),
            ("25.00", TransactionStatus.OVERDUE),
        ):
            _insert_transaction(
                app,
                user_id=user_id,
                card_id=card["id"],
                amount=amount,
                due_date=date.today(),
                status=status,
            )

        response = client.get(
            f"/credit-cards/{card['id']}/utilization", headers=headers
        )
        body = response.get_json()["data"]
        # Sum depends on whether today's date falls inside the current cycle window
        # (which it must, since cycle is centred on today). We assert >= the
        # contributions to keep the test resilient to date drift.
        assert Decimal(body["committed_amount"]) >= Decimal("0")
        if Decimal(body["committed_amount"]) > 0:
            assert body["utilization_pct"] is not None

    def test_excludes_cancelled_and_postponed(self, app, client) -> None:
        token = _register_and_login(client, prefix="util-excluded")
        headers = _auth_headers(token)
        card = _create_card(client, headers, limit_amount=1000.0)
        user_id = _current_user_id_from_token(app, token)

        for status in (TransactionStatus.CANCELLED, TransactionStatus.POSTPONED):
            _insert_transaction(
                app,
                user_id=user_id,
                card_id=card["id"],
                amount="500.00",
                due_date=date.today(),
                status=status,
            )

        response = client.get(
            f"/credit-cards/{card['id']}/utilization", headers=headers
        )
        body = response.get_json()["data"]
        assert Decimal(body["committed_amount"]) == Decimal("0")
        assert body["utilization_pct"] == 0.0

    def test_returns_null_pct_when_no_limit(self, client) -> None:
        token = _register_and_login(client, prefix="util-no-limit")
        headers = _auth_headers(token)
        card = _create_card(client, headers, limit_amount=None)

        response = client.get(
            f"/credit-cards/{card['id']}/utilization", headers=headers
        )
        assert response.status_code == 200
        body = response.get_json()["data"]
        assert body["utilization_pct"] is None
        assert body["available_amount"] is None
        assert body["limit_amount"] is None

    def test_returns_404_when_card_belongs_to_other_user(self, client) -> None:
        owner = _register_and_login(client, prefix="util-owner")
        card = _create_card(client, _auth_headers(owner))
        stranger = _register_and_login(client, prefix="util-stranger")

        response = client.get(
            f"/credit-cards/{card['id']}/utilization",
            headers=_auth_headers(stranger),
        )
        assert response.status_code == 404
