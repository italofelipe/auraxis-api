"""Multi-month trends and runway computation helpers.

Extracted from :class:`TransactionAnalyticsService` to keep the service module
focused on single-month aggregates and fit under the per-file LOC ceiling.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import case, func

from app.extensions.database import db
from app.models.transaction import (
    Transaction,
    TransactionImpactPolicy,
    TransactionStatus,
    TransactionType,
)
from app.models.wallet import Wallet

if TYPE_CHECKING:
    from app.application.services.transaction.query_types import (
        SurvivalClassification,
        SurvivalIndexResult,
        TransactionTrendsMonthEntry,
        TransactionTrendsResult,
    )


def compute_dashboard_trends(*, user_id: UUID, months: int) -> TransactionTrendsResult:
    """Compute monthly income/expense/balance for the last N months.

    Only months that have at least one PAID transaction are included. Results
    are ordered most-recent first.
    """
    today = date.today()
    month_starts: list[date] = []
    for offset in range(months):
        year = today.year
        month = today.month - offset
        while month <= 0:
            month += 12
            year -= 1
        month_starts.append(date(year, month, 1))

    series: list[TransactionTrendsMonthEntry] = []
    for month_start in month_starts:
        month_end = _last_day_of_month(month_start)
        row = (
            db.session.query(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Transaction.type == TransactionType.INCOME,
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("income"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Transaction.type == TransactionType.EXPENSE,
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("expenses"),
                func.count(Transaction.id).label("tx_count"),
            )
            .filter(
                Transaction.user_id == user_id,
                Transaction.deleted.is_(False),
                Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY,
                Transaction.status == TransactionStatus.PAID,
                Transaction.due_date >= month_start,
                Transaction.due_date <= month_end,
            )
            .one()
        )

        if int(row.tx_count or 0) == 0:
            continue

        income = float(row.income or 0)
        expenses = float(row.expenses or 0)
        series.append(
            {
                "month": month_start.strftime("%Y-%m"),
                "income": income,
                "expenses": expenses,
                "balance": round(income - expenses, 2),
            }
        )

    return {"months": months, "series": series}


def compute_survival_index(
    *, user_id: UUID, period_months: int = 3
) -> SurvivalIndexResult:
    """Compute the burn-rate survival index.

    ``total_assets / avg_monthly_expense`` = months of runway. The average is
    taken over the last ``period_months`` *complete* calendar months (current
    month is excluded to avoid partial-month skew).
    """
    today = date.today()

    assets_row = (
        db.session.query(func.coalesce(func.sum(Wallet.value), 0).label("total"))
        .filter(
            Wallet.user_id == user_id,
            Wallet.should_be_on_wallet.is_(True),
            Wallet.value.isnot(None),
        )
        .one()
    )
    total_assets = float(assets_row.total or 0)

    year = today.year
    anchor_month = today.month - period_months
    while anchor_month <= 0:
        anchor_month += 12
        year -= 1
    period_start = date(year, anchor_month, 1)
    period_end = today.replace(day=1) - timedelta(days=1)

    expense_row = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0).label("total"))
        .filter(
            Transaction.user_id == user_id,
            Transaction.deleted.is_(False),
            Transaction.type == TransactionType.EXPENSE,
            Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY,
            Transaction.status == TransactionStatus.PAID,
            Transaction.due_date >= period_start,
            Transaction.due_date <= period_end,
        )
        .one()
    )
    total_expense = float(expense_row.total or 0)
    avg_monthly_expense = round(total_expense / period_months, 2)

    if avg_monthly_expense == 0:
        return {
            "survival_months": None,
            "total_assets": round(total_assets, 2),
            "avg_monthly_expense": 0.0,
            "classification": None,
            "period_analyzed_months": period_months,
        }

    survival_months = round(total_assets / avg_monthly_expense, 2)
    return {
        "survival_months": survival_months,
        "total_assets": round(total_assets, 2),
        "avg_monthly_expense": avg_monthly_expense,
        "classification": classify_survival(survival_months),
        "period_analyzed_months": period_months,
    }


def _last_day_of_month(anchor: date) -> date:
    next_month = anchor.replace(day=28) + timedelta(days=4)
    return next_month.replace(day=1) - timedelta(days=1)


def classify_survival(months: float) -> SurvivalClassification:
    if months < 3:
        return "critical"
    if months < 6:
        return "attention"
    if months <= 12:
        return "comfortable"
    return "secure"


__all__ = [
    "classify_survival",
    "compute_dashboard_trends",
    "compute_survival_index",
]
