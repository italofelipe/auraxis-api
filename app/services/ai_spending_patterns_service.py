"""Cached "Radar de Gastos" (spending-patterns) service (#1455).

Historically the Radar de Gastos endpoint (``POST /ai/insights/spending-patterns``)
forwarded every request to auraxis-api-v2, which ran the LLM detection on demand —
and each call consumed the user's 1/day AI quota. Since the dashboard auto-fires on
login, that single daily quota was burned before the user did anything deliberate.

This service moves generation to a scheduled cron (``flask ai spending-patterns``)
that calls v2 server-to-server (no quota) and persists the result as an
``AIInsight`` of type ``spending_patterns``. The app then reads the cached analysis
via a quota-free read-only endpoint — mirroring the weekly-summary pattern.

Public surface:
  * :func:`call_v2_spending_patterns` — thin v2 HTTP client (also reused by the
    legacy on-demand proxy for DRY).
  * :func:`read_latest_spending_patterns` — read-only cache lookup.
  * :func:`generate_and_persist_spending_patterns` — cron-side generation.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import requests
from flask_jwt_extended import create_access_token

from app.application.services.transaction_query_service import TransactionQueryService
from app.extensions.database import db
from app.models.ai_insight import AIInsight, InsightType

log = logging.getLogger(__name__)

_V2_PATH = "/v2/insights/spending-patterns"
_TIMEOUT_SECONDS = 30.0
_PERIOD_DAYS = 90
_DEFAULT_MODEL = "v2-spending-patterns"
_EXPENSE_PAGE_SIZE = 500


class SpendingPatternsUpstreamError(RuntimeError):
    """Raised when the v2 spending-patterns service is unavailable or errored."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _v2_base_url() -> str:
    """Return the configured v2 base URL without a trailing slash (or empty)."""
    return os.getenv("AURAXIS_API_V2_BASE_URL", "").rstrip("/")


def call_v2_spending_patterns(
    *,
    transactions: list[dict[str, Any]],
    period_days: int,
    auth_header: str,
) -> tuple[int, dict[str, Any]]:
    """POST the LGPD-safe payload to auraxis-api-v2 and return ``(status, body)``.

    Raises:
        SpendingPatternsUpstreamError: when v2 is unconfigured or unreachable.
    """
    base_url = _v2_base_url()
    if not base_url:
        log.warning("spending_patterns.v2_unconfigured")
        raise SpendingPatternsUpstreamError(
            "Serviço de insights temporariamente indisponível.",
            status_code=503,
        )

    try:
        upstream = requests.post(
            f"{base_url}{_V2_PATH}",
            json={"transactions": transactions, "period_days": period_days},
            headers={"Authorization": auth_header},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        log.warning("spending_patterns.v2_unreachable", exc_info=True)
        raise SpendingPatternsUpstreamError(
            "Serviço de insights temporariamente indisponível.",
            status_code=503,
        ) from exc

    try:
        body: dict[str, Any] = upstream.json()
    except ValueError:
        body = {}

    return upstream.status_code, body


def read_latest_spending_patterns(user_id: UUID) -> dict[str, Any]:
    """Read the latest cached spending-patterns insight for *user_id*.

    NEVER calls the LLM and NEVER consumes quota — generation happens only in the
    scheduled cron. When no cached analysis exists yet, returns an empty patterns
    list with ``generated_at=None`` so the UI can render a "will be generated"
    state.
    """
    latest: AIInsight | None = (
        db.session.query(AIInsight)
        .filter_by(user_id=user_id, insight_type=InsightType.spending_patterns)
        .order_by(AIInsight.created_at.desc())
        .first()
    )

    if latest is None:
        return {
            "patterns": [],
            "generated_at": None,
            "period_label": None,
            "model": "",
            "cost_usd": 0.0,
            "tokens_used": 0,
        }

    return {
        "patterns": _decode_patterns(latest.content),
        "generated_at": latest.created_at.isoformat() if latest.created_at else None,
        "period_label": latest.period_label,
        "model": latest.model,
        "cost_usd": float(latest.cost_usd),
        "tokens_used": latest.tokens_used,
    }


def generate_and_persist_spending_patterns(
    user_id: UUID,
    *,
    anchor_date: date,
) -> dict[str, Any]:
    """Generate (via v2) and persist the spending-patterns insight for a user.

    Pulls the last ~90 days of expenses, builds the LGPD-safe payload, mints a
    server-to-server access token (so v2's premium gate passes) and calls v2
    WITHOUT consuming the per-user AI quota. On success the patterns are cached
    as an ``AIInsight`` of type ``spending_patterns``. When v2 returns no patterns
    (empty/error) nothing is persisted and ``persisted=False`` is returned.

    Returns:
        ``{"patterns": [...], "cost_usd": float, "tokens_used": int,
           "cached": False, "persisted": bool}``
    """
    end = anchor_date
    start = anchor_date - timedelta(days=_PERIOD_DAYS)
    transactions = _build_expense_payload(user_id=user_id, start=start, end=end)

    auth_header = f"Bearer {create_access_token(str(user_id))}"
    status_code, body = call_v2_spending_patterns(
        transactions=transactions,
        period_days=_PERIOD_DAYS,
        auth_header=auth_header,
    )

    if status_code >= 400:
        raise SpendingPatternsUpstreamError(
            "Falha ao gerar o radar de gastos.",
            status_code=status_code,
        )

    patterns = body.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        # Nothing actionable returned — do not persist an empty analysis.
        return {
            "patterns": [],
            "cost_usd": 0.0,
            "tokens_used": 0,
            "cached": False,
            "persisted": False,
        }

    cost_usd = _safe_float(body.get("cost_usd"))
    tokens_used = _safe_int(body.get("tokens_used") or body.get("tokens_total"))
    model = str(body.get("model") or _DEFAULT_MODEL)

    _persist(
        user_id=user_id,
        patterns=patterns,
        period_start=start,
        period_end=end,
        period_label=anchor_date.isoformat(),
        model=model,
        tokens_used=tokens_used,
        cost_usd=cost_usd,
    )

    return {
        "patterns": patterns,
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
        "cached": False,
        "persisted": True,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_expense_payload(
    *,
    user_id: UUID,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Return an LGPD-safe list of expense rows for the v2 detector.

    Only the fields v2 needs are forwarded: amount, occurred_on, category. No
    titles, descriptions or free-text are sent.
    """
    from sqlalchemy import desc

    from app.models.transaction import Transaction

    query_service = TransactionQueryService.with_defaults(user_id)
    result = query_service.get_expense_period(
        start_date=start,
        end_date=end,
        page=1,
        per_page=_EXPENSE_PAGE_SIZE,
        ordering_clause=desc(Transaction.due_date),
    )

    payload: list[dict[str, Any]] = []
    for expense in result["expenses"]:
        payload.append(
            {
                "amount": expense["amount"],
                "occurred_on": expense["due_date"],
                "category": expense.get("category"),
                "kind": "expense",
            }
        )
    return payload


def _persist(
    *,
    user_id: UUID,
    patterns: list[Any],
    period_start: date,
    period_end: date,
    period_label: str,
    model: str,
    tokens_used: int,
    cost_usd: float,
) -> AIInsight:
    insight = AIInsight(
        user_id=user_id,
        content=json.dumps({"patterns": patterns}, ensure_ascii=False),
        insight_type=InsightType.spending_patterns,
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        model=model,
        tokens_used=tokens_used,
        cost_usd=Decimal(str(cost_usd)),
        previous_insight_id=None,
    )
    db.session.add(insight)
    db.session.commit()
    return insight


def _decode_patterns(content: str) -> list[Any]:
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError):
        return []
    if isinstance(parsed, dict):
        patterns = parsed.get("patterns")
        return patterns if isinstance(patterns, list) else []
    return parsed if isinstance(parsed, list) else []


def _safe_float(value: object) -> float:
    try:
        return float(value or 0)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


__all__ = [
    "SpendingPatternsUpstreamError",
    "call_v2_spending_patterns",
    "generate_and_persist_spending_patterns",
    "read_latest_spending_patterns",
]
