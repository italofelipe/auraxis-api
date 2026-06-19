"""GraphQL parity tests for CreditCard queries.

Covers:
- creditCards list returns enriched fields (bank, benefits, etc)
- creditCardBill mirrors REST endpoint shape
- creditCardUtilization mirrors REST endpoint shape
- Auth required (regression test_graphql_auth_everywhere also covers)
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


def _gql(client, query, token, variables=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "X-API-Contract": "v2",
        "Content-Type": "application/json",
    }
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )


def _create_card_rest(client, token, **fields):
    payload = {
        "name": fields.get("name", "Nubank"),
        "brand": fields.get("brand", "mastercard"),
        "limit_amount": fields.get("limit_amount", 5000.0),
        "closing_day": fields.get("closing_day", 10),
        "due_day": fields.get("due_day", 15),
        "bank": fields.get("bank", "Nubank"),
        "benefits": fields.get("benefits", ["Cashback 1%"]),
    }
    response = client.post(
        "/credit-cards",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
    )
    assert response.status_code == 201
    return response.get_json()["data"]["credit_card"]


class TestCreditCardsQuery:
    def test_lists_user_cards_with_enriched_fields(self, client) -> None:
        token = _register_and_login(client, prefix="gql-cards-list")
        card = _create_card_rest(client, token, name="Nubank", bank="Nubank")

        response = _gql(
            client,
            """
            query {
              creditCards {
                creditCards {
                  id
                  name
                  brand
                  limitAmount
                  closingDay
                  dueDay
                  bank
                  benefits
                }
                total
              }
            }
            """,
            token,
        )
        assert response.status_code == 200
        body = response.get_json()
        assert "errors" not in body or not body["errors"]
        data = body["data"]["creditCards"]
        assert data["total"] == 1
        assert data["creditCards"][0]["id"] == card["id"]
        assert data["creditCards"][0]["bank"] == "Nubank"
        assert data["creditCards"][0]["benefits"] == ["Cashback 1%"]

    def test_sensitive_card_fields_are_not_exposed_in_schema(self, client) -> None:
        token = _register_and_login(client, prefix="gql-cards-sensitive")
        _create_card_rest(client, token, name="Nubank", bank="Nubank")

        response = _gql(
            client,
            """
            query {
              creditCards {
                creditCards {
                  id
                  lastFourDigits
                  validityDate
                }
              }
            }
            """,
            token,
        )

        assert response.status_code == 400
        errors = response.get_json()["errors"]
        assert any("lastFourDigits" in error["message"] for error in errors)
        assert any("validityDate" in error["message"] for error in errors)

    def test_returns_empty_list_when_user_has_no_cards(self, client) -> None:
        token = _register_and_login(client, prefix="gql-cards-empty")
        response = _gql(
            client,
            "query { creditCards { creditCards { id } total } }",
            token,
        )
        body = response.get_json()
        assert body["data"]["creditCards"]["total"] == 0
        assert body["data"]["creditCards"]["creditCards"] == []

    def test_requires_auth(self, client) -> None:
        response = client.post(
            "/graphql",
            json={"query": "query { creditCards { total } }"},
            headers={"Content-Type": "application/json", "X-API-Contract": "v2"},
        )
        body = response.get_json()
        # Either 401 status or a GraphQL auth error in the body
        assert response.status_code == 401 or (body.get("errors"))


class TestCreditCardBillQuery:
    def test_returns_bill_for_month(self, app, client) -> None:
        token = _register_and_login(client, prefix="gql-bill")
        card = _create_card_rest(client, token, closing_day=10, due_day=15)

        # Inject a transaction in cycle.
        from flask_jwt_extended import decode_token

        with app.app_context():
            user_id = UUID(decode_token(token)["sub"])
            tx = Transaction(
                user_id=user_id,
                credit_card_id=UUID(card["id"]),
                title="lunch",
                amount=Decimal("42.50"),
                due_date=date(2026, 5, 5),
                status=TransactionStatus.PAID,
                type=TransactionType.EXPENSE,
            )
            db.session.add(tx)
            db.session.commit()

        response = _gql(
            client,
            """
            query GetBill($cardId: UUID!, $month: String!) {
              creditCardBill(cardId: $cardId, month: $month) {
                cycle { startDate endDate dueDate status }
                totalAmount
                paidAmount
                pendingAmount
                transactions { id title amount }
              }
            }
            """,
            token,
            variables={"cardId": card["id"], "month": "2026-05"},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert "errors" not in body or not body["errors"]
        bill = body["data"]["creditCardBill"]
        assert bill["cycle"]["startDate"] == "2026-04-11"
        assert bill["cycle"]["endDate"] == "2026-05-10"
        assert bill["cycle"]["dueDate"] == "2026-05-15"
        assert Decimal(bill["totalAmount"]) == Decimal("42.50")
        assert Decimal(bill["paidAmount"]) == Decimal("42.50")
        assert len(bill["transactions"]) == 1

    def test_returns_null_for_cross_user_card(self, client) -> None:
        owner = _register_and_login(client, prefix="gql-bill-owner")
        card = _create_card_rest(client, owner)
        stranger = _register_and_login(client, prefix="gql-bill-stranger")

        response = _gql(
            client,
            """
            query GetBill($cardId: UUID!) {
              creditCardBill(cardId: $cardId, month: "2026-05") {
                totalAmount
              }
            }
            """,
            stranger,
            variables={"cardId": card["id"]},
        )
        body = response.get_json()
        assert body["data"]["creditCardBill"] is None


class TestCreditCardUtilizationQuery:
    def test_returns_utilization(self, client) -> None:
        token = _register_and_login(client, prefix="gql-util")
        card = _create_card_rest(client, token, limit_amount=2000.0)

        response = _gql(
            client,
            """
            query GetUtil($cardId: UUID!) {
              creditCardUtilization(cardId: $cardId) {
                cycle { startDate endDate }
                committedAmount
                availableAmount
                limitAmount
                utilizationPct
              }
            }
            """,
            token,
            variables={"cardId": card["id"]},
        )
        assert response.status_code == 200
        body = response.get_json()
        util = body["data"]["creditCardUtilization"]
        assert Decimal(util["committedAmount"]) == Decimal("0")
        assert Decimal(util["limitAmount"]) == Decimal("2000.00")
        assert util["utilizationPct"] == 0.0

    def test_returns_null_pct_when_no_limit(self, client) -> None:
        token = _register_and_login(client, prefix="gql-util-no-limit")
        card = _create_card_rest(client, token, limit_amount=None)

        response = _gql(
            client,
            """
            query GetUtil($cardId: UUID!) {
              creditCardUtilization(cardId: $cardId) {
                limitAmount
                utilizationPct
                availableAmount
              }
            }
            """,
            token,
            variables={"cardId": card["id"]},
        )
        util = response.get_json()["data"]["creditCardUtilization"]
        assert util["utilizationPct"] is None
        assert util["limitAmount"] is None
        assert util["availableAmount"] is None
