"""Integration tests: expense-period query follows the bill cycle.

``get_expense_period`` powers the monthly expense listing (and its counts).
When the requested range is a full calendar month, credit-card expenses must
be grouped by the bill cycle they belong to — keeping items and counts
consistent with the Cartões/fatura view — while non-card expenses stay on the
calendar month. Custom/partial ranges keep the raw ``due_date`` filter.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from app.application.services.transaction_application_service import (
    TransactionApplicationService,
)
from app.application.services.transaction_query_service import (
    TransactionQueryDependencies,
    TransactionQueryService,
)
from app.extensions.database import db
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.services.transaction_analytics_service import TransactionAnalyticsService


def _make_user() -> UUID:
    user = User(
        name="exp-comp",
        email=f"exp-comp-{uuid4().hex[:8]}@email.com",
        password="hash",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _make_card(user_id: UUID, *, closing_day: int, due_day: int) -> UUID:
    card = CreditCard(
        user_id=user_id,
        name="card",
        brand="mastercard",
        closing_day=closing_day,
        due_day=due_day,
    )
    db.session.add(card)
    db.session.commit()
    return card.id


def _make_expense(
    user_id: UUID, *, due_date: date, title: str, card_id: UUID | None = None
) -> None:
    db.session.add(
        Transaction(
            id=uuid4(),
            user_id=user_id,
            credit_card_id=card_id,
            title=title,
            amount=Decimal("100.00"),
            type=TransactionType.EXPENSE,
            status=TransactionStatus.PENDING,
            due_date=due_date,
            currency="BRL",
            source="manual",
        )
    )
    db.session.commit()


def _service(user_id: UUID) -> TransactionQueryService:
    return TransactionQueryService(
        user_id=user_id,
        dependencies=TransactionQueryDependencies(
            transaction_application_service_factory=lambda _uid: cast(
                TransactionApplicationService, object()
            ),
            analytics_service_factory=lambda _uid: cast(
                TransactionAnalyticsService, object()
            ),
        ),
    )


class TestExpensePeriodFollowsBillCycle:
    def test_card_expense_after_closing_counts_in_following_month(
        self, app: Any
    ) -> None:
        with app.app_context():
            user_id = _make_user()
            card_id = _make_card(user_id, closing_day=10, due_day=15)
            # July cycle 2026-06-11 .. 2026-07-10 → June-19 belongs to July.
            _make_expense(
                user_id, card_id=card_id, due_date=date(2026, 6, 19), title="card-jun19"
            )

            july = _service(user_id).get_expense_period(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
                page=1,
                per_page=10,
                ordering_clause=Transaction.created_at.asc(),
            )
            june = _service(user_id).get_expense_period(
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 30),
                page=1,
                per_page=10,
                ordering_clause=Transaction.created_at.asc(),
            )

        assert [item["title"] for item in july["expenses"]] == ["card-jun19"]
        assert july["counts"]["expense_transactions"] == 1
        assert july["pagination"]["total"] == 1
        # Not in June (its calendar month).
        assert june["counts"]["expense_transactions"] == 0
        assert june["expenses"] == []

    def test_non_card_expense_stays_on_calendar_month(self, app: Any) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_card(user_id, closing_day=10, due_day=15)
            _make_expense(user_id, due_date=date(2026, 7, 5), title="rent-jul")
            _make_expense(user_id, due_date=date(2026, 6, 30), title="rent-jun")

            july = _service(user_id).get_expense_period(
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
                page=1,
                per_page=10,
                ordering_clause=Transaction.created_at.asc(),
            )

        assert [item["title"] for item in july["expenses"]] == ["rent-jul"]
        assert july["counts"]["expense_transactions"] == 1

    def test_partial_range_keeps_raw_due_date(self, app: Any) -> None:
        with app.app_context():
            user_id = _make_user()
            card_id = _make_card(user_id, closing_day=10, due_day=15)
            _make_expense(
                user_id, card_id=card_id, due_date=date(2026, 6, 19), title="card-jun19"
            )

            partial = _service(user_id).get_expense_period(
                start_date=date(2026, 6, 15),
                end_date=date(2026, 6, 20),
                page=1,
                per_page=10,
                ordering_clause=Transaction.created_at.asc(),
            )

        assert [item["title"] for item in partial["expenses"]] == ["card-jun19"]
        assert partial["counts"]["expense_transactions"] == 1
