"""Regression: list/aggregation reads must not truncate to the first page.

Bug history: the credit-cards trend chart and rail (auraxis-web) rendered zeroed
values because the backend list endpoint returned only the first page (default
``per_page`` = 10) while the client aggregated over that truncated slice
(fixes #1082 / #1083, client-side ``listAllTransactions``). The backend contract
that fix depends on is exercised here:

1. Pagination metadata reports the *full* matching ``total`` (and page count), so a
   client can iterate every page and reconstruct the complete set.
2. Month aggregates (``income_total`` / ``expense_total``) are computed over ALL
   matching rows — never just the current page.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from app.application.services.transaction_query_service import TransactionQueryService
from app.extensions.database import db
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User

_PER_PAGE = 10
_EXPENSE_COUNT = 25
_EXPENSE_AMOUNT = Decimal("10.00")
_INCOME_AMOUNT = Decimal("1000.00")
_TOTAL = _EXPENSE_COUNT + 1  # + one income row


def _seed_user_with_month_transactions(month: date) -> UUID:
    user = User(name="Pag", email=f"pag-{uuid4().hex[:8]}@email.com", password="hash")
    db.session.add(user)
    db.session.commit()

    rows = [
        Transaction(
            id=uuid4(),
            user_id=user.id,
            title=f"Expense {index}",
            amount=_EXPENSE_AMOUNT,
            type=TransactionType.EXPENSE,
            status=TransactionStatus.PENDING,
            due_date=month.replace(day=1 + (index % 27)),
            currency="BRL",
            source="manual",
        )
        for index in range(_EXPENSE_COUNT)
    ]
    rows.append(
        Transaction(
            id=uuid4(),
            user_id=user.id,
            title="Salary",
            amount=_INCOME_AMOUNT,
            type=TransactionType.INCOME,
            status=TransactionStatus.PENDING,
            due_date=month.replace(day=5),
            currency="BRL",
            source="manual",
        )
    )
    db.session.add_all(rows)
    db.session.commit()
    return user.id


def test_month_summary_aggregates_over_all_rows_not_page(app) -> None:
    with app.app_context():
        user_id = _seed_user_with_month_transactions(date(2026, 3, 1))
        service = TransactionQueryService.with_defaults(user_id)

        result = service.get_month_summary(month="2026-03", page=1, per_page=_PER_PAGE)

        # Aggregations must reflect ALL rows, never the truncated first page.
        assert result["expense_total"] == float(_EXPENSE_AMOUNT) * _EXPENSE_COUNT
        assert result["income_total"] == float(_INCOME_AMOUNT)

        paginated = result["paginated"]
        assert paginated["total"] == _TOTAL
        assert paginated["page_size"] == _PER_PAGE
        assert len(paginated["data"]) == _PER_PAGE
        assert paginated["has_next_page"] is True


def test_month_summary_last_page_returns_remaining_rows(app) -> None:
    with app.app_context():
        user_id = _seed_user_with_month_transactions(date(2026, 3, 1))
        service = TransactionQueryService.with_defaults(user_id)

        last_page = (_TOTAL + _PER_PAGE - 1) // _PER_PAGE  # 3
        result = service.get_month_summary(
            month="2026-03", page=last_page, per_page=_PER_PAGE
        )

        paginated = result["paginated"]
        assert paginated["total"] == _TOTAL
        assert len(paginated["data"]) == _TOTAL - _PER_PAGE * (last_page - 1)  # 6
        assert paginated["has_next_page"] is False


def test_active_transactions_pagination_reports_full_total(app) -> None:
    with app.app_context():
        user_id = _seed_user_with_month_transactions(date(2026, 3, 1))
        service = TransactionQueryService.with_defaults(user_id)

        common = dict(
            per_page=_PER_PAGE,
            transaction_type=None,
            status=None,
            start_date=None,
            end_date=None,
            tag_id=None,
            account_id=None,
            credit_card_id=None,
        )
        page1 = service.get_active_transactions(page=1, **common)
        assert int(page1["pagination"]["total"]) == _TOTAL
        assert len(page1["items"]) == _PER_PAGE

        # Page 2 must return the *next* slice — proving no first-page truncation.
        page2 = service.get_active_transactions(page=2, **common)
        page1_titles = {item["title"] for item in page1["items"]}
        page2_titles = {item["title"] for item in page2["items"]}
        assert page1_titles.isdisjoint(page2_titles)
        assert len(page2["items"]) == _PER_PAGE
