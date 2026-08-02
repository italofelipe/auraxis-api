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
# Longest upstream description kept in the exception message / cron log.
_MAX_UPSTREAM_DETAIL_CHARS = 200
# Validation errors reported per failure — enough to diagnose, not a dump.
_MAX_VALIDATION_ERRORS = 3


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

    if not transactions:
        # v2 requires at least one transaction (``min_length=1``); posting an
        # empty list earns a 422 that used to surface as a generic domain error
        # and turned "nothing to analyse" into a failed weekly job (#1596).
        log.info(
            "spending_patterns.no_expenses user=%s period=%s",
            user_id,
            anchor_date.isoformat(),
        )
        return _no_analysis_result()

    # Server-to-server token for the internal v2 call. The token_use=service
    # claim tells v2 to skip its per-user session (active_jti) revocation — this
    # cron token has no user session — while signature and account-block checks
    # still apply on the v2 side. See auraxis-api-v2#97.
    service_token = create_access_token(
        str(user_id), additional_claims={"token_use": "service"}
    )
    auth_header = f"Bearer {service_token}"
    status_code, body = call_v2_spending_patterns(
        transactions=transactions,
        period_days=_PERIOD_DAYS,
        auth_header=auth_header,
    )

    if status_code >= 400:
        # The cron's only trace of this failure is the exception message, so it
        # has to name the cause. #1596 stayed open for eight days because a 401
        # "Token revoked." from v2 looked exactly like a 422 or a 500 in the job
        # log, in the diagnostics artifact and in the auto-opened issue.
        summary = _describe_upstream_failure(status_code, body)
        log.warning("spending_patterns.v2_rejected %s", summary)
        raise SpendingPatternsUpstreamError(
            f"Falha ao gerar o radar de gastos ({summary}).",
            status_code=status_code,
        )

    patterns = body.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        # Nothing actionable returned — do not persist an empty analysis.
        return _no_analysis_result()

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


def _no_analysis_result() -> dict[str, Any]:
    """Result for "there is nothing to cache" — not an error, nothing persisted."""
    return {
        "patterns": [],
        "cost_usd": 0.0,
        "tokens_used": 0,
        "cached": False,
        "persisted": False,
    }


def _describe_upstream_failure(status_code: int, body: dict[str, Any]) -> str:
    """Summarise a v2 rejection for the cron log — never echoing request data.

    FastAPI's 422 body repeats the rejected ``input`` (transaction amounts), so
    only the error ``type`` and the field ``loc`` are reported; a plain string
    ``detail`` (``"Token revoked."``) is safe and is the most useful signal.
    """
    detail = body.get("detail")
    summary = ""

    if isinstance(detail, str):
        summary = detail.strip()
    elif isinstance(detail, list):
        summary = "; ".join(
            described
            for item in detail[:_MAX_VALIDATION_ERRORS]
            if (described := _describe_validation_error(item))
        )

    if not summary:
        return f"HTTP {status_code}"
    return f"HTTP {status_code}: {summary[:_MAX_UPSTREAM_DETAIL_CHARS]}"


def _describe_validation_error(item: object) -> str:
    """Render one pydantic error as ``field.path: error_type`` (no values)."""
    if not isinstance(item, dict):
        return ""
    location = item.get("loc")
    error_type = str(item.get("type") or "invalid")
    if not isinstance(location, list | tuple) or not location:
        return error_type
    parts = [str(part) for part in location if str(part) != "body"]
    return f"{'.'.join(parts)}: {error_type}" if parts else error_type


def _build_expense_payload(
    *,
    user_id: UUID,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Return an LGPD-safe list of expense rows for the v2 detector.

    Only the fields v2 needs are forwarded: amount, occurred_on, category. No
    titles, descriptions or free-text are sent. Rows v2 would reject (it declares
    ``amount: float = Field(gt=0)``) are dropped here — otherwise a single zeroed
    expense 422s the whole user's radar.
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
        amount = _positive_amount(expense["amount"])
        if amount is None:
            continue
        payload.append(
            {
                "amount": amount,
                "occurred_on": expense["due_date"],
                "category": expense.get("category"),
                "kind": "expense",
            }
        )
    return payload


def _positive_amount(value: object) -> float | None:
    """Coerce to a strictly positive float, or ``None`` when v2 would reject it."""
    try:
        amount = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


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
