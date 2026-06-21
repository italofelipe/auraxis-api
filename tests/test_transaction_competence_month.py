"""Unit tests for the credit-card competence-month helpers.

Pure functions — no DB. These back the "Transações follow the bill" fix:
credit-card transactions must be grouped by the bill cycle that contains
their ``due_date``, not by the calendar month of ``due_date``.

Covers:
- ``bill_month_for`` — the ``YYYY-MM`` of the cycle a purchase falls into.
- ``month_span_if_full_calendar_month`` — detect a full-calendar-month range.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.extensions.database import db
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.services.credit_card_bill_service import (
    bill_month_for,
    build_competence_month_filter,
    month_span_if_full_calendar_month,
)


def _make_user() -> UUID:
    user = User(
        name="comp-user",
        email=f"comp-{uuid4().hex[:8]}@email.com",
        password="x",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _make_card(
    user_id: UUID,
    *,
    closing_day: int | None,
    due_day: int | None,
) -> UUID:
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


def _make_tx(
    user_id: UUID,
    *,
    due_date: date,
    card_id: UUID | None = None,
    tx_type: TransactionType = TransactionType.EXPENSE,
    title: str = "tx",
) -> UUID:
    tx = Transaction(
        user_id=user_id,
        credit_card_id=card_id,
        title=title,
        amount=Decimal("100.00"),
        due_date=due_date,
        status=TransactionStatus.PENDING,
        type=tx_type,
    )
    db.session.add(tx)
    db.session.commit()
    return tx.id


def _titles_matching(user_id: UUID, predicate: Any) -> set[str]:
    rows = (
        Transaction.query.filter_by(user_id=user_id, deleted=False)
        .filter(predicate)
        .all()
    )
    return {row.title for row in rows}


class TestBillMonthForAfterClosing:
    """A purchase AFTER the closing day belongs to the FOLLOWING month's bill."""

    def test_purchase_after_closing_rolls_to_next_month(self) -> None:
        # Card closes on the 10th; a purchase on 2026-06-19 is past closing,
        # so it lands on the cycle ending 2026-07-10 → July's bill.
        assert (
            bill_month_for(due_date=date(2026, 6, 19), closing_day=10, due_day=15)
            == "2026-07"
        )


class TestBillMonthForOnOrBeforeClosing:
    """A purchase ON or BEFORE the closing day stays in the CURRENT month."""

    def test_purchase_before_closing_stays_in_current_month(self) -> None:
        # Card closes on the 20th; a purchase on 2026-06-19 is before closing,
        # so it lands on the cycle ending 2026-06-20 → June's bill.
        assert (
            bill_month_for(due_date=date(2026, 6, 19), closing_day=20, due_day=25)
            == "2026-06"
        )

    def test_purchase_exactly_on_closing_day_stays_in_current_month(self) -> None:
        assert (
            bill_month_for(due_date=date(2026, 6, 20), closing_day=20, due_day=25)
            == "2026-06"
        )


class TestBillMonthForYearBoundary:
    """December purchases after closing roll into January of the next year."""

    def test_december_purchase_after_closing_rolls_to_january(self) -> None:
        assert (
            bill_month_for(due_date=date(2026, 12, 20), closing_day=10, due_day=15)
            == "2027-01"
        )


class TestBillMonthForMonthEndClamp:
    """closing_day 31 clamps to the last valid day in short months."""

    def test_closing_day_31_in_february_keeps_current_month(self) -> None:
        # Feb 2026 has 28 days; a day-31 card closes Feb 28, so a purchase on
        # 2026-02-15 is before closing → February's bill.
        assert (
            bill_month_for(due_date=date(2026, 2, 15), closing_day=31, due_day=10)
            == "2026-02"
        )


class TestMonthSpanIfFullCalendarMonth:
    """Detect a [start, end] range that covers exactly one calendar month."""

    def test_full_month_returns_year_month_string(self) -> None:
        assert (
            month_span_if_full_calendar_month(date(2026, 6, 1), date(2026, 6, 30))
            == "2026-06"
        )

    def test_full_february_non_leap_returns_string(self) -> None:
        assert (
            month_span_if_full_calendar_month(date(2026, 2, 1), date(2026, 2, 28))
            == "2026-02"
        )

    def test_partial_range_returns_none(self) -> None:
        assert (
            month_span_if_full_calendar_month(date(2026, 6, 1), date(2026, 6, 15))
            is None
        )

    def test_not_starting_on_first_returns_none(self) -> None:
        assert (
            month_span_if_full_calendar_month(date(2026, 6, 2), date(2026, 6, 30))
            is None
        )

    def test_spanning_two_months_returns_none(self) -> None:
        assert (
            month_span_if_full_calendar_month(date(2026, 6, 1), date(2026, 7, 31))
            is None
        )

    def test_none_start_returns_none(self) -> None:
        assert month_span_if_full_calendar_month(None, date(2026, 6, 30)) is None

    def test_none_end_returns_none(self) -> None:
        assert month_span_if_full_calendar_month(date(2026, 6, 1), None) is None


class TestBuildCompetenceMonthFilter:
    """``build_competence_month_filter`` groups card txns by bill cycle.

    Card transactions are matched by the closing cycle that contains their
    ``due_date``; non-card transactions and incomes are matched by the
    calendar month.
    """

    def test_card_purchase_after_closing_matches_following_month(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            # Closes on the 10th: July cycle is 2026-06-11 .. 2026-07-10.
            card_id = _make_card(user_id, closing_day=10, due_day=15)
            # Purchase 2026-06-19 (June calendar) is past June closing →
            # belongs to July's bill.
            _make_tx(
                user_id, due_date=date(2026, 6, 19), card_id=card_id, title="jun19-card"
            )
            # Purchase 2026-07-20 is past July closing → August's bill.
            _make_tx(
                user_id, due_date=date(2026, 7, 20), card_id=card_id, title="jul20-card"
            )

            predicate = build_competence_month_filter(user_id, "2026-07")
            matched = _titles_matching(user_id, predicate)

        assert "jun19-card" in matched
        assert "jul20-card" not in matched

    def test_non_card_and_income_follow_calendar_month(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_card(user_id, closing_day=10, due_day=15)
            _make_tx(user_id, due_date=date(2026, 7, 5), title="jul-nocard")
            _make_tx(user_id, due_date=date(2026, 6, 30), title="jun-nocard")
            _make_tx(
                user_id,
                due_date=date(2026, 7, 9),
                tx_type=TransactionType.INCOME,
                title="jul-income",
            )

            predicate = build_competence_month_filter(user_id, "2026-07")
            matched = _titles_matching(user_id, predicate)

        assert matched == {"jul-nocard", "jul-income"}

    def test_card_without_closing_day_uses_calendar_month(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            card_id = _make_card(user_id, closing_day=None, due_day=None)
            _make_tx(
                user_id, due_date=date(2026, 7, 15), card_id=card_id, title="jul-card"
            )
            _make_tx(
                user_id, due_date=date(2026, 6, 15), card_id=card_id, title="jun-card"
            )

            predicate = build_competence_month_filter(user_id, "2026-07")
            matched = _titles_matching(user_id, predicate)

        assert matched == {"jul-card"}

    def test_only_owners_cards_scope_the_filter(self, app) -> None:
        # A purchase on another user's card must not leak into this user's
        # competence filter results.
        with app.app_context():
            user_id = _make_user()
            other_id = _make_user()
            other_card = _make_card(other_id, closing_day=10, due_day=15)
            _make_tx(
                other_id,
                due_date=date(2026, 6, 19),
                card_id=other_card,
                title="other-card",
            )

            predicate = build_competence_month_filter(user_id, "2026-07")
            # Scope by user explicitly to mirror production list queries.
            matched = _titles_matching(user_id, predicate)

        assert matched == set()
