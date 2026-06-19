"""Deleting a credit card removes the debts/installments charged to it (#1459).

Regression: creating a card + an installment expense, then deleting the card,
used to leave the installments in the transactions list pointing at a card that
no longer exists.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from flask_jwt_extended import decode_token

from app.extensions.database import db
from app.models.transaction import Transaction, TransactionStatus, TransactionType


def _register_and_login(client, *, prefix: str) -> str:
    suffix = uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    register = client.post(
        "/auth/register",
        json={"name": f"user-{suffix}", "email": email, "password": "StrongPass@123"},
    )
    assert register.status_code == 201
    login = client.post(
        "/auth/login", json={"email": email, "password": "StrongPass@123"}
    )
    assert login.status_code == 200
    return login.get_json()["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


def _create_card(client, headers) -> dict:
    resp = client.post(
        "/credit-cards",
        json={
            "name": "Nubank",
            "brand": "mastercard",
            "limit_amount": 5000.0,
            "closing_day": 10,
            "due_day": 15,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.get_json()["data"]["credit_card"]


def _user_id(app, token: str) -> str:
    with app.app_context():
        return str(decode_token(token)["sub"])


def _add_installments(app, *, user_id: str, card_id: str, n: int) -> str:
    """Insert *n* installments of one parcelled expense charged to the card."""
    group_id = uuid4()
    with app.app_context():
        for i in range(n):
            db.session.add(
                Transaction(
                    user_id=UUID(user_id),
                    credit_card_id=UUID(card_id),
                    installment_group_id=group_id,
                    title=f"Parcela {i + 1}/{n}",
                    amount=Decimal("100.00"),
                    due_date=date(2026, 6, 1),
                    status=TransactionStatus.PENDING,
                    type=TransactionType.EXPENSE,
                )
            )
        db.session.commit()
    return str(group_id)


class TestCreditCardDeleteCascade:
    def test_deleting_card_soft_deletes_its_installments(self, app, client) -> None:
        token = _register_and_login(client, prefix="cc-del")
        headers = _headers(token)
        card = _create_card(client, headers)
        user_id = _user_id(app, token)
        _add_installments(app, user_id=user_id, card_id=card["id"], n=3)

        # The debt is visible before deleting the card.
        before = client.get("/transactions", headers=headers)
        assert before.status_code == 200

        resp = client.delete(f"/credit-cards/{card['id']}", headers=headers)
        assert resp.status_code == 200

        # All installments are soft-deleted and unlinked from the card.
        with app.app_context():
            rows = Transaction.query.filter_by(user_id=UUID(user_id)).all()
            assert len(rows) == 3
            assert all(r.deleted is True for r in rows)
            assert all(r.credit_card_id is None for r in rows)

    def test_deleting_card_keeps_other_cards_transactions(self, app, client) -> None:
        token = _register_and_login(client, prefix="cc-del-keep")
        headers = _headers(token)
        user_id = _user_id(app, token)
        card_a = _create_card(client, headers)
        card_b = _create_card(client, headers)
        _add_installments(app, user_id=user_id, card_id=card_a["id"], n=2)
        _add_installments(app, user_id=user_id, card_id=card_b["id"], n=2)

        resp = client.delete(f"/credit-cards/{card_a['id']}", headers=headers)
        assert resp.status_code == 200

        with app.app_context():
            active = Transaction.query.filter_by(
                user_id=UUID(user_id), deleted=False
            ).all()
            # Only card B's transactions survive.
            assert len(active) == 2
            assert all(r.credit_card_id == UUID(card_b["id"]) for r in active)

    def test_delete_missing_card_returns_404(self, app, client) -> None:
        token = _register_and_login(client, prefix="cc-del-404")
        resp = client.delete(f"/credit-cards/{uuid4()}", headers=_headers(token))
        assert resp.status_code == 404
