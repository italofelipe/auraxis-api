"""Shared read model for the AI insight history (#1653).

`GET /ai/insights/history` and the `aiInsightHistory` GraphQL query each carried
their own copy of the same query — same filter, same ordering, same pagination,
written twice. That is exactly how REST/GraphQL parity rots: a filter added on
one side silently never reaches the other.

This module owns the query. Both protocols call ``list_user_insights`` and only
serialise the rows in their own shape, so parity holds by construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.extensions.database import db
from app.models.ai_insight import AIInsight, InsightType

DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 20
MAX_PER_PAGE = 50

_VALID_PERIOD_TYPES = ", ".join(member.value for member in InsightType)
PERIOD_TYPE_ERROR_MESSAGE = (
    f"Parâmetro 'period_type' inválido. Use um de: {_VALID_PERIOD_TYPES}."
)


class AIInsightHistoryValidationError(ValueError):
    """Raised when a caller passes an unsupported filter value."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = "VALIDATION_ERROR"


@dataclass(frozen=True)
class AIInsightHistoryPage:
    """One page of insights plus the pagination echo both protocols return."""

    items: list[AIInsight]
    page: int
    per_page: int
    total: int


def normalize_pagination(page: Any, per_page: Any) -> tuple[int, int]:
    """Clamp pagination inputs to the supported window.

    Invalid/absent values fall back to the defaults; ``page`` never goes below 1
    (a negative OFFSET used to be reachable through GraphQL) and ``per_page`` is
    capped at ``MAX_PER_PAGE``.
    """
    try:
        parsed_page = max(1, int(page)) if page is not None else DEFAULT_PAGE
    except (TypeError, ValueError):
        parsed_page = DEFAULT_PAGE
    try:
        parsed_per_page = (
            min(MAX_PER_PAGE, max(1, int(per_page)))
            if per_page is not None
            else DEFAULT_PER_PAGE
        )
    except (TypeError, ValueError):
        parsed_per_page = DEFAULT_PER_PAGE
    return parsed_page, parsed_per_page


def normalize_period_type(raw_value: Any) -> InsightType | None:
    """Map a raw ``period_type`` filter to ``InsightType`` (``None`` when absent).

    Raises ``AIInsightHistoryValidationError`` for an unknown value instead of
    silently ignoring the filter and returning the whole history.
    """
    if raw_value is None:
        return None
    value = str(raw_value).strip().lower()
    if not value:
        return None
    try:
        return InsightType(value)
    except ValueError as exc:
        raise AIInsightHistoryValidationError(PERIOD_TYPE_ERROR_MESSAGE) from exc


def normalize_period_label(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


def list_user_insights(
    user_id: UUID,
    *,
    page: Any = DEFAULT_PAGE,
    per_page: Any = DEFAULT_PER_PAGE,
    period_type: Any = None,
    period_label: Any = None,
) -> AIInsightHistoryPage:
    """Return the user's insights, newest first, with optional period filters.

    Both filters are additive and optional — omitting them reproduces the
    previous behaviour exactly. ``(user_id, insight_type, period_label)`` is
    covered by ``ix_ai_insights_user_type_period``.
    """
    normalized_page, normalized_per_page = normalize_pagination(page, per_page)
    insight_type = normalize_period_type(period_type)
    label = normalize_period_label(period_label)

    query = db.session.query(AIInsight).filter(AIInsight.user_id == user_id)
    if insight_type is not None:
        query = query.filter(AIInsight.insight_type == insight_type)
    if label is not None:
        query = query.filter(AIInsight.period_label == label)

    total = query.count()
    rows = (
        query.order_by(AIInsight.created_at.desc())
        .offset((normalized_page - 1) * normalized_per_page)
        .limit(normalized_per_page)
        .all()
    )

    return AIInsightHistoryPage(
        items=list(rows),
        page=normalized_page,
        per_page=normalized_per_page,
        total=total,
    )


__all__ = [
    "AIInsightHistoryPage",
    "AIInsightHistoryValidationError",
    "DEFAULT_PAGE",
    "DEFAULT_PER_PAGE",
    "MAX_PER_PAGE",
    "PERIOD_TYPE_ERROR_MESSAGE",
    "list_user_insights",
    "normalize_pagination",
    "normalize_period_label",
    "normalize_period_type",
]
