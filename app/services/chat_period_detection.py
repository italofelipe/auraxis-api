"""Deterministic pt-BR period detection for the finance chat (#1548).

The Ask-anything chat used to anchor its snapshot on TODAY only, so
"quanto foi o salário de julho?" could never be answered. This module parses
period references in the user's question — month names, "mês passado",
"semana passada", "ontem", "YYYY-MM" — and returns the anchor date the chat
context should be built around. Pure regex/date arithmetic: zero LLM cost and
fully unit-testable.
"""

from __future__ import annotations

import re
import unicodedata
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

_MONTHS_PT = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_MONTH_LABELS_PT = {v: k for k, v in _MONTHS_PT.items()}

_YYYY_MM_RE = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])\b")
_MONTH_NAME_RE = re.compile(
    r"\b(" + "|".join(_MONTHS_PT) + r")\b(?:\s+de\s+(20\d{2}))?",
)


@dataclass(frozen=True)
class ChatPeriodResolution:
    """Anchor + human label for the period referenced in a chat question."""

    anchor: date
    label: str
    matched: bool


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _month_anchor(year: int, month: int, *, today: date) -> date:
    """Anchor inside the referenced month: its last day, capped at today."""
    last_day = date(year, month, monthrange(year, month)[1])
    return (
        min(last_day, today) if (year, month) == (today.year, today.month) else last_day
    )


def _month_label(year: int, month: int) -> str:
    return f"{_MONTH_LABELS_PT[month]}/{year}"


def detect_chat_period(question: str, *, today: date) -> ChatPeriodResolution:
    """Resolve the period a pt-BR finance question refers to.

    Precedence: explicit ``YYYY-MM`` > month name (optionally "de YYYY") >
    "mês passado" > "semana passada" > "ontem" > default (today / current
    month). A bare month name resolves to the nearest non-future occurrence
    (e.g. asking "dezembro" in July refers to last December).
    """
    normalized = _normalize(question or "")

    explicit = _YYYY_MM_RE.search(normalized)
    if explicit:
        year, month = int(explicit.group(1)), int(explicit.group(2))
        return ChatPeriodResolution(
            anchor=_month_anchor(year, month, today=today),
            label=_month_label(year, month),
            matched=True,
        )

    if "mes passado" in normalized:
        first_of_month = today.replace(day=1)
        previous = first_of_month - timedelta(days=1)
        return ChatPeriodResolution(
            anchor=previous,
            label=_month_label(previous.year, previous.month),
            matched=True,
        )

    month_match = _MONTH_NAME_RE.search(normalized)
    if month_match:
        month = _MONTHS_PT[month_match.group(1)]
        year_raw = month_match.group(2)
        if year_raw:
            year = int(year_raw)
        else:
            year = today.year if month <= today.month else today.year - 1
        return ChatPeriodResolution(
            anchor=_month_anchor(year, month, today=today),
            label=_month_label(year, month),
            matched=True,
        )

    if "semana passada" in normalized:
        anchor = today - timedelta(days=7)
        return ChatPeriodResolution(
            anchor=anchor,
            label=f"semana passada ({anchor.isoformat()})",
            matched=True,
        )

    if "ontem" in normalized:
        anchor = today - timedelta(days=1)
        return ChatPeriodResolution(
            anchor=anchor,
            label=f"ontem ({anchor.isoformat()})",
            matched=True,
        )

    return ChatPeriodResolution(
        anchor=today,
        label=_month_label(today.year, today.month),
        matched=False,
    )


__all__ = ["ChatPeriodResolution", "detect_chat_period"]
