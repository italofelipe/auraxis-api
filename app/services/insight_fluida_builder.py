"""Deterministic structured fields for the "Insights Fluida" screen (#1501).

The Fluida screen (auraxis-web / auraxis-app) renders structured blocks that the
backend CALCULATES from the user's real transactions — the LLM only writes prose
(``summary``); every number here is anchored to the ledger.

This module is purely additive: it computes ``paragraphs``, ``retro``, ``series``
and ``highlights`` and exposes :func:`enrich_insight_payload`, which composes them
into an existing insight payload dict without removing or mutating prior keys.

Aggregation rules mirror the canonical analytics layer
(:mod:`app.services.weekly_summary`): outflow = ``PAID`` ``EXPENSE`` on
``due_date``, excluding soft-deleted rows and ``impact_policy == CARDS_ONLY``.
Amounts are decimal currency units (``Numeric(12, 2)``) — never cents.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func

from app.extensions.database import db
from app.models.transaction import (
    Transaction,
    TransactionImpactPolicy,
    TransactionStatus,
    TransactionType,
)
from app.services.weekly_summary import _aggregate_range

Sign = Literal["pos", "neg", "neutral"]

_DAILY_WINDOW = 7
_WEEKLY_WINDOW = 6
_MAX_HIGHLIGHTS = 3
# A single block (no blank-line breaks) longer than this is split on sentence
# boundaries so the Fluida cards stay short; a lone short sentence is kept whole.
_LONG_BLOCK_THRESHOLD = 90

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def build_paragraphs(summary: str | None) -> list[str]:
    """Split AI prose into short paragraphs for the Fluida layout.

    Blank lines are the primary delimiter. A single long block with no blank
    lines is split on sentence boundaries so no card holds a wall of text.
    """
    if not summary or not summary.strip():
        return []

    blocks = [block.strip() for block in re.split(r"\n\s*\n", summary)]
    blocks = [block for block in blocks if block]

    if len(blocks) <= 1 and blocks and len(blocks[0]) > _LONG_BLOCK_THRESHOLD:
        sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(blocks[0])]
        return [s for s in sentences if s]

    return blocks


def _outflow(*, user_id: UUID, start: date, end: date) -> float:
    """Outflow (expense) total for [start, end], reusing weekly_summary."""
    _income, expense, _count = _aggregate_range(user_id=user_id, start=start, end=end)
    return round(expense, 2)


def _sign_for_spend(*, current: float, previous: float) -> Sign:
    """Spending more than the comparison baseline is a negative signal."""
    if current == previous:
        return "neutral"
    return "neg" if current > previous else "pos"


def build_retro(*, user_id: UUID, anchor: date) -> list[dict[str, Any]]:
    """Outflow retrospective: yesterday, day-before and this-week-vs-last.

    Belongs to the ``general`` dimension. ``value`` is a decimal amount; ``sign``
    encodes whether the movement is favourable (less spending = ``pos``).
    """
    yesterday = anchor - timedelta(days=1)
    daybefore = anchor - timedelta(days=2)

    yesterday_total = _outflow(user_id=user_id, start=yesterday, end=yesterday)
    daybefore_total = _outflow(user_id=user_id, start=daybefore, end=daybefore)

    cur_week_start = anchor - timedelta(days=anchor.weekday())
    cur_week_end = cur_week_start + timedelta(days=6)
    prev_week_start = cur_week_start - timedelta(days=7)
    prev_week_end = cur_week_start - timedelta(days=1)

    cur_week_total = _outflow(user_id=user_id, start=cur_week_start, end=cur_week_end)
    prev_week_total = _outflow(
        user_id=user_id, start=prev_week_start, end=prev_week_end
    )
    week_delta = round(cur_week_total - prev_week_total, 2)

    return [
        {
            "key": "yesterday",
            "label": "Ontem",
            "value": yesterday_total,
            "caption": "Saídas de ontem",
            "sign": _sign_for_spend(current=yesterday_total, previous=daybefore_total),
        },
        {
            "key": "daybefore",
            "label": "Anteontem",
            "value": daybefore_total,
            "caption": "Saídas de anteontem",
            "sign": "neutral",
        },
        {
            "key": "vs_week",
            "label": "Semana vs. anterior",
            "value": week_delta,
            "caption": "Variação de saídas da semana",
            "sign": _sign_for_spend(current=cur_week_total, previous=prev_week_total),
        },
    ]


def build_series(*, user_id: UUID, anchor: date) -> dict[str, list[float]]:
    """Outflow series: daily over the last 7 days, weekly over the last 6 weeks.

    Both windows end on (and include) the anchor. ``daily[-1]`` and
    ``weekly[-1]`` are the anchor day / anchor week respectively.
    """
    daily: list[float] = []
    for offset in range(_DAILY_WINDOW - 1, -1, -1):
        day = anchor - timedelta(days=offset)
        daily.append(_outflow(user_id=user_id, start=day, end=day))

    cur_week_start = anchor - timedelta(days=anchor.weekday())
    weekly: list[float] = []
    for offset in range(_WEEKLY_WINDOW - 1, -1, -1):
        week_start = cur_week_start - timedelta(days=7 * offset)
        week_end = week_start + timedelta(days=6)
        weekly.append(_outflow(user_id=user_id, start=week_start, end=week_end))

    return {"daily": daily, "weekly": weekly}


def _month_bounds(anchor: date) -> tuple[date, date]:
    start = anchor.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1)
    else:
        next_month = start.replace(month=start.month + 1)
    return start, next_month - timedelta(days=1)


def _paid_rows(
    *,
    user_id: UUID,
    tx_type: TransactionType,
    start: date,
    end: date,
) -> list[Transaction]:
    rows: list[Transaction] = (
        db.session.query(Transaction)
        .filter(
            Transaction.user_id == user_id,
            Transaction.deleted.is_(False),
            Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY,
            Transaction.status == TransactionStatus.PAID,
            Transaction.type == tx_type,
            Transaction.due_date >= start,
            Transaction.due_date <= end,
        )
        .order_by(Transaction.amount.desc())
        .all()
    )
    return rows


def build_highlights(*, user_id: UUID, anchor: date) -> list[dict[str, Any]]:
    """Per-theme highlights for the month containing *anchor* (2-3 items)."""
    start, end = _month_bounds(anchor)
    highlights: list[dict[str, Any]] = []

    expenses = _paid_rows(
        user_id=user_id, tx_type=TransactionType.EXPENSE, start=start, end=end
    )
    if expenses:
        biggest = expenses[0]
        highlights.append(
            {
                "label": "Maior gasto do mês",
                "value": round(float(biggest.amount), 2),
                "sub": biggest.title or "",
            }
        )

    incomes = _paid_rows(
        user_id=user_id, tx_type=TransactionType.INCOME, start=start, end=end
    )
    if len(incomes) == 1:
        only_credit = incomes[0]
        highlights.append(
            {
                "label": "Único crédito",
                "value": round(float(only_credit.amount), 2),
                "sub": only_credit.title or "",
            }
        )
    elif len(incomes) > 1:
        total_income = (
            db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter(
                Transaction.user_id == user_id,
                Transaction.deleted.is_(False),
                Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY,
                Transaction.status == TransactionStatus.PAID,
                Transaction.type == TransactionType.INCOME,
                Transaction.due_date >= start,
                Transaction.due_date <= end,
            )
            .scalar()
        )
        highlights.append(
            {
                "label": "Maior crédito do mês",
                "value": round(float(incomes[0].amount), 2),
                "sub": incomes[0].title or "",
            }
        )
        # Keep total available for a possible second income highlight.
        if len(highlights) < _MAX_HIGHLIGHTS:
            highlights.append(
                {
                    "label": "Total de créditos",
                    "value": round(float(Decimal(str(total_income or 0))), 2),
                    "sub": f"{len(incomes)} entradas",
                }
            )

    return highlights[:_MAX_HIGHLIGHTS]


def _resolve_anchor(payload: dict[str, Any], anchor: date | None) -> date:
    if anchor is not None:
        return anchor
    raw_start = payload.get("period_start")
    if isinstance(raw_start, str) and raw_start:
        try:
            return date.fromisoformat(raw_start)
        except ValueError:
            pass
    return date.today()


def enrich_insight_payload(
    payload: dict[str, Any],
    *,
    user_id: UUID,
    anchor: date | None = None,
) -> dict[str, Any]:
    """Add the structured Fluida fields to *payload* (additive, in place).

    ``paragraphs`` is derived from the AI ``summary``; ``retro`` (general
    dimension), ``series`` and ``highlights`` (per theme) are computed from the
    user's transactions. Pre-existing keys are never removed or modified — the
    REST/GraphQL contract stays backward compatible.

    When *anchor* is omitted it defaults to the payload's ``period_start`` so the
    calculation window aligns with the insight period.
    """
    resolved_anchor = _resolve_anchor(payload, anchor)

    summary = payload.get("summary")
    payload["paragraphs"] = build_paragraphs(
        summary if isinstance(summary, str) else None
    )
    payload["retro"] = build_retro(user_id=user_id, anchor=resolved_anchor)
    payload["series"] = build_series(user_id=user_id, anchor=resolved_anchor)
    payload["highlights"] = build_highlights(user_id=user_id, anchor=resolved_anchor)
    return payload


__all__ = [
    "build_highlights",
    "build_paragraphs",
    "build_retro",
    "build_series",
    "enrich_insight_payload",
]
