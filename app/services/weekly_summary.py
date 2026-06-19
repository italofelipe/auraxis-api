"""Weekly summary computation — current/previous week comparison + time series.

B13: Contrato de resumo semanal com comparativo e série temporal para gráfico.
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

if TYPE_CHECKING:
    from app.application.services.transaction.query_types import (
        WeeklyComparison,
        WeeklyPeriodTotals,
        WeeklySummaryResult,
        WeeklySummarySeriesEntry,
    )

_VALID_PRESET_DAYS = {"1m": 30, "3m": 90, "6m": 180}


def _week_bounds(anchor: date) -> tuple[date, date]:
    """Return Monday–Sunday of the ISO week that contains *anchor*."""
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)


def _aggregate_range(
    *,
    user_id: UUID,
    start: date,
    end: date,
) -> tuple[float, float, int]:
    """Return (income, expense, count) for PAID transactions in [start, end]."""
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
            ).label("expense"),
            func.count(Transaction.id).label("tx_count"),
        )
        .filter(
            Transaction.user_id == user_id,
            Transaction.deleted.is_(False),
            Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY,
            Transaction.status == TransactionStatus.PAID,
            Transaction.due_date >= start,
            Transaction.due_date <= end,
        )
        .one()
    )
    return float(row.income or 0), float(row.expense or 0), int(row.tx_count or 0)


def _safe_delta_percent(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 2)


def _build_daily_series(
    *,
    user_id: UUID,
    start: date,
    end: date,
) -> list[WeeklySummarySeriesEntry]:
    rows = (
        db.session.query(
            Transaction.due_date.label("day"),
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
            ).label("expense"),
        )
        .filter(
            Transaction.user_id == user_id,
            Transaction.deleted.is_(False),
            Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY,
            Transaction.status == TransactionStatus.PAID,
            Transaction.due_date >= start,
            Transaction.due_date <= end,
        )
        .group_by(Transaction.due_date)
        .order_by(Transaction.due_date)
        .all()
    )
    index: dict[date, tuple[float, float]] = {
        r.day: (float(r.income or 0), float(r.expense or 0)) for r in rows
    }
    series: list[WeeklySummarySeriesEntry] = []
    cursor = start
    while cursor <= end:
        income, expense = index.get(cursor, (0.0, 0.0))
        series.append(
            {
                "date": cursor.isoformat(),
                "income": income,
                "expense": expense,
                "balance": round(income - expense, 2),
            }
        )
        cursor += timedelta(days=1)
    return series


def _build_weekly_series(
    *,
    user_id: UUID,
    start: date,
    end: date,
) -> list[WeeklySummarySeriesEntry]:
    # Align start to Monday
    week_start = start - timedelta(days=start.weekday())
    series: list[WeeklySummarySeriesEntry] = []
    cursor = week_start
    while cursor <= end:
        week_end = min(cursor + timedelta(days=6), end)
        income, expense, _ = _aggregate_range(
            user_id=user_id, start=cursor, end=week_end
        )
        series.append(
            {
                "date": cursor.isoformat(),
                "income": income,
                "expense": expense,
                "balance": round(income - expense, 2),
            }
        )
        cursor += timedelta(days=7)
    return series


def compute_weekly_summary(
    *,
    user_id: UUID,
    period: str = "1m",
    start_date: date | None = None,
    end_date: date | None = None,
) -> WeeklySummaryResult:
    today = date.today()

    if start_date is not None and end_date is not None:
        series_start = start_date
        series_end = end_date
        period_label = "custom"
    else:
        days = _VALID_PRESET_DAYS.get(period, 30)
        series_end = today
        series_start = today - timedelta(days=days - 1)
        period_label = period

    cur_week_start, cur_week_end = _week_bounds(today)
    prev_week_start = cur_week_start - timedelta(days=7)
    prev_week_end = cur_week_start - timedelta(days=1)

    cur_income, cur_expense, cur_count = _aggregate_range(
        user_id=user_id, start=cur_week_start, end=cur_week_end
    )
    prev_income, prev_expense, prev_count = _aggregate_range(
        user_id=user_id, start=prev_week_start, end=prev_week_end
    )

    span_days = (series_end - series_start).days + 1
    if span_days <= 31:
        series = _build_daily_series(
            user_id=user_id, start=series_start, end=series_end
        )
    else:
        series = _build_weekly_series(
            user_id=user_id, start=series_start, end=series_end
        )

    current_week: WeeklyPeriodTotals = {
        "start": cur_week_start.isoformat(),
        "end": cur_week_end.isoformat(),
        "income": round(cur_income, 2),
        "expense": round(cur_expense, 2),
        "balance": round(cur_income - cur_expense, 2),
        "transaction_count": cur_count,
    }
    previous_week: WeeklyPeriodTotals = {
        "start": prev_week_start.isoformat(),
        "end": prev_week_end.isoformat(),
        "income": round(prev_income, 2),
        "expense": round(prev_expense, 2),
        "balance": round(prev_income - prev_expense, 2),
        "transaction_count": prev_count,
    }
    comparison: WeeklyComparison = {
        "income_delta": round(cur_income - prev_income, 2),
        "income_delta_percent": _safe_delta_percent(cur_income, prev_income),
        "expense_delta": round(cur_expense - prev_expense, 2),
        "expense_delta_percent": _safe_delta_percent(cur_expense, prev_expense),
        "balance_delta": round(
            (cur_income - cur_expense) - (prev_income - prev_expense), 2
        ),
        "balance_delta_percent": _safe_delta_percent(
            cur_income - cur_expense, prev_income - prev_expense
        ),
    }

    return {
        "current_week": current_week,
        "previous_week": previous_week,
        "comparison": comparison,
        "series": series,
        "period": period_label,
        "series_start": series_start.isoformat(),
        "series_end": series_end.isoformat(),
    }


__all__ = ["compute_weekly_summary"]
