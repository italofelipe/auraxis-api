"""Period-aware financial context snapshots for AI insights.

The builder computes deterministic facts from internal transaction data before
any LLM call. It deliberately emits sanitized dictionaries instead of model
instances so prompts and audit logs do not receive user PII or raw IDs.
"""

from __future__ import annotations

import json
import logging
import os
import re
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID

from app.models.budget import Budget
from app.models.credit_card import CreditCard
from app.models.goal import Goal
from app.models.goal_contribution import GoalContribution
from app.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.models.wallet import Wallet
from app.services.credit_card_bill_service import compute_utilization
from app.services.investor_profile_targets import (
    AllocationDiagnosis,
    evaluate_allocation,
)
from app.services.market_rates_provider import (
    MarketRatesProvider,
    get_default_market_rates_provider,
)

INSIGHT_DIMENSIONS: tuple[str, ...] = (
    "general",
    "transactions",
    "credit_cards",
    "goals",
    "budgets",
    "wallet",
)
"""Closed enum of dimension labels assigned to each AI insight item.

Decided on 2026-05-17 (MVP-3 wiki): each insight item must declare which
surface it belongs to so contextual pages can filter, while the global
`/insights` hub renders all dimensions grouped.
"""

_SNAPSHOT_VERSION = "financial_insight_snapshot.v1"
_CURRENCY = "BRL"
_TIMEZONE = "America/Sao_Paulo"
_GOAL_PACE_WINDOW_DAYS = 90

# Hard cap on serialized snapshot size sent to the LLM (Sprint 5 obs-1).
# When exceeded, `truncate_snapshot()` reduces large lists deterministically
# while preserving the structural backbone (schema_version, current_period,
# comparisons). Override via AI_SNAPSHOT_MAX_BYTES env for cost experiments.
DEFAULT_MAX_SNAPSHOT_BYTES = 12 * 1024
MAX_SNAPSHOT_BYTES = int(
    os.getenv("AI_SNAPSHOT_MAX_BYTES", str(DEFAULT_MAX_SNAPSHOT_BYTES))
)

_log = logging.getLogger(__name__)
_MONEY_QUANT = Decimal("0.01")
_PERCENT_QUANT = Decimal("0.01")
_EMAIL_MASK = "[email]"
_MAX_EMAIL_TOKEN_LENGTH = 320
_EMAIL_LOCAL_SYMBOLS = "._%+-"
_EMAIL_DOMAIN_SYMBOLS = "-_"
_CPF_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
_LONG_NUMBER_RE = re.compile(r"\b\d{8,}\b")
_RiskPenalty = tuple[int, dict[str, Any]]


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(_MONEY_QUANT)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _money_str(value: object) -> str:
    return f"{_money(value):.2f}"


def _percent_str(value: object) -> str:
    try:
        return f"{Decimal(str(value or '0')).quantize(_PERCENT_QUANT):.2f}"
    except (InvalidOperation, ValueError):
        return "0.00"


def _safe_pct(numerator: Decimal, denominator: Decimal) -> str:
    if denominator == 0:
        return "0.00"
    return _percent_str(numerator / denominator * Decimal("100"))


def _is_email_candidate_char(char: str) -> bool:
    return char.isalnum() or char == "@" or char in _EMAIL_LOCAL_SYMBOLS


def _is_email_local_char(char: str) -> bool:
    return char.isalnum() or char in _EMAIL_LOCAL_SYMBOLS


def _is_email_domain_char(char: str) -> bool:
    return char.isalnum() or char in _EMAIL_DOMAIN_SYMBOLS


def _strip_email_boundary_dots(token: str) -> tuple[str, str, str]:
    prefix = ""
    suffix = ""
    candidate = token

    while candidate.startswith("."):
        prefix += "."
        candidate = candidate[1:]
    while candidate.endswith("."):
        suffix = "." + suffix
        candidate = candidate[:-1]

    return prefix, candidate, suffix


def _looks_like_email(candidate: str) -> bool:
    if candidate.count("@") != 1:
        return False

    local_part, domain = candidate.split("@", 1)
    if (
        not local_part
        or not domain
        or len(local_part) > 64
        or len(domain) > 253
        or "." not in domain
        or local_part.startswith(".")
        or local_part.endswith(".")
    ):
        return False

    if not all(_is_email_local_char(char) for char in local_part):
        return False

    labels = domain.split(".")
    return all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(_is_email_domain_char(char) for char in label)
        for label in labels
    )


def _redact_email_token(token: str) -> str:
    prefix, candidate, suffix = _strip_email_boundary_dots(token)
    if "@" not in candidate:
        return token
    if len(candidate) > _MAX_EMAIL_TOKEN_LENGTH or candidate.count("@") > 1:
        return f"{prefix}{_EMAIL_MASK}{suffix}"
    if _looks_like_email(candidate):
        return f"{prefix}{_EMAIL_MASK}{suffix}"
    return token


def _redact_email_tokens(text: str) -> str:
    redacted: list[str] = []
    token_chars: list[str] = []

    for char in text:
        if _is_email_candidate_char(char):
            token_chars.append(char)
            continue

        if token_chars:
            redacted.append(_redact_email_token("".join(token_chars)))
            token_chars = []
        redacted.append(char)

    if token_chars:
        redacted.append(_redact_email_token("".join(token_chars)))

    return "".join(redacted)


def _sanitize_text(value: object, *, max_length: int = 120) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    text = _redact_email_tokens(text)
    text = _CPF_RE.sub("[cpf]", text)
    text = _LONG_NUMBER_RE.sub("[number]", text)
    text = " ".join(text.split())
    if len(text) > max_length:
        return text[: max_length - 1].rstrip() + "..."
    return text


def _enum_value(value: object) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value)


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _datetime_after(value: datetime | None, since: datetime) -> bool:
    return value is not None and _naive_utc(value) > since


def _same_day_previous_year(anchor_date: date) -> date | None:
    """Return the same calendar day a year before, or None when invalid (Feb 29)."""
    try:
        return anchor_date.replace(year=anchor_date.year - 1)
    except ValueError:
        return None


def _same_day_previous_month(anchor_date: date) -> date | None:
    previous_year = anchor_date.year
    previous_month = anchor_date.month - 1
    if previous_month == 0:
        previous_year -= 1
        previous_month = 12

    days_in_previous_month = monthrange(previous_year, previous_month)[1]
    if anchor_date.day > days_in_previous_month:
        return None
    return date(previous_year, previous_month, anchor_date.day)


def _month_bounds(anchor_date: date) -> tuple[date, date]:
    last_day = monthrange(anchor_date.year, anchor_date.month)[1]
    return date(anchor_date.year, anchor_date.month, 1), date(
        anchor_date.year,
        anchor_date.month,
        last_day,
    )


def _week_bounds(anchor_date: date) -> tuple[date, date]:
    start = anchor_date - timedelta(days=anchor_date.weekday())
    return start, start + timedelta(days=6)


def _date_period(start: date, end: date, label: str) -> dict[str, str]:
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "label": label,
    }


def _insight_contract() -> dict[str, Any]:
    return {
        "required_dimensions": list(INSIGHT_DIMENSIONS),
        "absence_evidence_prefix": "data_quality.domain_presence",
    }


def _risk_flag(
    *,
    code: str,
    severity: str,
    dimension: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "dimension": dimension,
        "evidence": evidence,
    }


def _financial_health_grade(score: int) -> str:
    if score >= 80:
        return "healthy"
    if score >= 60:
        return "attention"
    return "critical"


def _goal_pace_assessment(
    *,
    remaining: Decimal,
    required_monthly_pace: Decimal | None,
    observed_monthly_pace: Decimal,
    has_target_date: bool,
    has_contribution_history: bool,
) -> tuple[str, str]:
    if remaining <= 0:
        return "completed", "goal_total"
    if not has_target_date:
        return "insufficient_data", "missing_target_date"
    if not has_contribution_history:
        return "insufficient_data", "no_contribution_history"
    if required_monthly_pace is None:
        return "insufficient_data", "missing_required_pace"
    if observed_monthly_pace >= required_monthly_pace:
        return "on_track", "goal_total_and_90d_contributions"
    return "behind", "goal_total_and_90d_contributions"


def _transaction_risk_penalties(
    *,
    balance: Decimal,
    income: Decimal,
    pending: Decimal,
    overdue: Decimal,
) -> list[_RiskPenalty]:
    penalties: list[_RiskPenalty] = []
    if balance < 0:
        penalties.append(
            (
                30,
                _risk_flag(
                    code="negative_paid_balance",
                    severity="high",
                    dimension="general",
                    evidence=["current_period.paid.balance"],
                ),
            )
        )
    if overdue > 0:
        penalties.append(
            (
                25,
                _risk_flag(
                    code="overdue_expenses",
                    severity="high",
                    dimension="transactions",
                    evidence=["current_period.commitments.overdue_expense_total"],
                ),
            )
        )
    if pending > 0:
        penalty, code, severity = (
            (20, "future_commitment_pressure", "medium")
            if income == 0 or pending > max(balance, Decimal("0.00"))
            else (5, "future_commitments_open", "low")
        )
        penalties.append(
            (
                penalty,
                _risk_flag(
                    code=code,
                    severity=severity,
                    dimension="transactions",
                    evidence=[
                        "current_period.commitments.pending_expense_total",
                        "current_period.paid.balance",
                    ],
                ),
            )
        )
    return penalties


def _budget_risk_penalties(budgets: object) -> list[_RiskPenalty]:
    if not isinstance(budgets, list):
        return []
    penalties: list[_RiskPenalty] = []
    for index, budget in enumerate(budgets):
        if not isinstance(budget, dict):
            continue
        utilization = _money(budget.get("utilization_pct"))
        if bool(budget.get("exceeded")):
            penalties.append(
                (
                    15,
                    _risk_flag(
                        code="budget_exceeded",
                        severity="medium",
                        dimension="budgets",
                        evidence=[f"budgets.{index}.exceeded"],
                    ),
                )
            )
        elif utilization >= 90:
            penalties.append(
                (
                    8,
                    _risk_flag(
                        code="budget_near_limit",
                        severity="low",
                        dimension="budgets",
                        evidence=[f"budgets.{index}.utilization_pct"],
                    ),
                )
            )
    return penalties


def _credit_card_risk_penalties(cards: object) -> list[_RiskPenalty]:
    if not isinstance(cards, list):
        return []
    penalties: list[_RiskPenalty] = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            continue
        utilization = _money(card.get("utilization_pct"))
        if utilization >= 95:
            penalty, code, severity = (
                25,
                "credit_card_utilization_critical",
                "high",
            )
        elif utilization >= 80:
            penalty, code, severity = 15, "high_credit_card_utilization", "medium"
        else:
            continue
        penalties.append(
            (
                penalty,
                _risk_flag(
                    code=code,
                    severity=severity,
                    dimension="credit_cards",
                    evidence=[f"credit_cards.{index}.utilization_pct"],
                ),
            )
        )
    return penalties


def _goal_risk_penalties(goals: object) -> list[_RiskPenalty]:
    if not isinstance(goals, list):
        return []
    penalties: list[_RiskPenalty] = []
    for index, goal in enumerate(goals):
        if not isinstance(goal, dict) or goal.get("pace_assessment") != "behind":
            continue
        penalties.append(
            (
                10,
                _risk_flag(
                    code="goal_pace_gap",
                    severity="medium",
                    dimension="goals",
                    evidence=[
                        f"goals.{index}.required_monthly_pace",
                        f"goals.{index}.observed_monthly_pace_90d",
                    ],
                ),
            )
        )
    return penalties


_PROJECTION_HORIZONS: tuple[int, ...] = (3, 6, 12)


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _annual_pct_to_monthly_rate(annual_pct: Decimal) -> Decimal:
    """Convert an annual percentage (e.g. 12.0) to an equivalent monthly rate."""
    base = Decimal(1) + (annual_pct / Decimal(100))
    if base <= 0:
        return Decimal(0)
    return base ** (Decimal(1) / Decimal(12)) - Decimal(1)


def _wallet_monthly_rate(wallet: dict[str, Any]) -> tuple[Decimal, str]:
    """Return (monthly_rate, basis). Observed weighted return, else CDI fallback."""
    items = wallet.get("items") if isinstance(wallet, dict) else None
    weighted_num = Decimal(0)
    total = Decimal(0)
    for item in items or []:
        if not isinstance(item, dict):
            continue
        value = _money(item.get("current_value"))
        if value <= 0:
            continue
        weighted_num += value * _decimal(item.get("annual_rate"))
        total += value
    if total > 0 and weighted_num > 0:
        return _annual_pct_to_monthly_rate(weighted_num / total), "observed"
    benchmark = wallet.get("benchmark") if isinstance(wallet, dict) else None
    cdi = benchmark.get("cdi_monthly_pct") if isinstance(benchmark, dict) else None
    if cdi:
        return _decimal(cdi) / Decimal(100), "cdi_fallback"
    return Decimal(0), "none"


def _fv_lump_sum(present_value: Decimal, rate: Decimal, months: int) -> Decimal:
    return present_value * (Decimal(1) + rate) ** months


def _fv_monthly_contribution(amount: Decimal, rate: Decimal, months: int) -> Decimal:
    if rate == 0:
        return amount * Decimal(months)
    return amount * (((Decimal(1) + rate) ** months - Decimal(1)) / rate)


def _wallet_projection(
    wallet: dict[str, Any], rate: Decimal, horizons: tuple[int, ...]
) -> dict[str, Any] | None:
    total_value = (
        _money(wallet.get("total_value")) if isinstance(wallet, dict) else Decimal(0)
    )
    if total_value <= 0:
        return None
    block: dict[str, Any] = {"current_value": _money_str(total_value)}
    for h in horizons:
        block[f"horizon_{h}m"] = _money_str(_fv_lump_sum(total_value, rate, h))
    return block


def _goal_projection_entry(
    goal: dict[str, Any], horizons: tuple[int, ...]
) -> tuple[dict[str, Any], Decimal | None]:
    current = _money(goal.get("current_amount"))
    observed = _money(goal.get("observed_monthly_pace_90d"))
    required_raw = goal.get("required_monthly_pace")
    required = _money(required_raw) if required_raw is not None else None
    entry: dict[str, Any] = {
        "title": goal.get("title") or "Meta",
        "current_amount": _money_str(current),
        "observed_monthly_pace_90d": _money_str(observed),
        "required_monthly_pace": _money_str(required) if required is not None else None,
    }
    for h in horizons:
        entry[f"horizon_{h}m_observed"] = _money_str(current + observed * h)
        if required is not None:
            entry[f"horizon_{h}m_required"] = _money_str(current + required * h)
    return entry, required


def _combined_scenario(
    *,
    required: Decimal,
    margin: Decimal,
    rate: Decimal,
    basis: str,
    horizons: tuple[int, ...],
) -> dict[str, Any]:
    combined: dict[str, Any] = {
        "monthly_goal_contribution": _money_str(required),
        "monthly_investment": _money_str(margin),
        "investment_rate_basis": basis,
    }
    for h in horizons:
        goal_part = required * h
        invest_part = _fv_monthly_contribution(margin, rate, h)
        combined[f"horizon_{h}m"] = _money_str(goal_part + invest_part)
    return combined


def _compute_projections(
    *,
    wallet: dict[str, Any],
    goals: list[dict[str, Any]],
    available_margin: Decimal,
    horizons: tuple[int, ...] = _PROJECTION_HORIZONS,
) -> dict[str, Any]:
    """Deterministic 3/6/12-month projections for wallet, goals and a combined
    "save X + invest Y" scenario. Every figure is snapshot-anchored so the LLM
    can cite ``projections.*`` instead of fabricating numbers (#1394)."""
    rate, basis = _wallet_monthly_rate(wallet if isinstance(wallet, dict) else {})
    payload: dict[str, Any] = {
        "horizons_months": list(horizons),
        "rate_basis": basis,
        "monthly_rate_pct": f"{(rate * Decimal(100)):.4f}",
    }

    wallet_block = _wallet_projection(wallet, rate, horizons)
    if wallet_block is not None:
        payload["wallet"] = wallet_block

    goal_projections: list[dict[str, Any]] = []
    required_for_combined: Decimal | None = None
    for goal in goals or []:
        if not isinstance(goal, dict):
            continue
        entry, required = _goal_projection_entry(goal, horizons)
        goal_projections.append(entry)
        if required_for_combined is None and required is not None and required > 0:
            required_for_combined = required
    if goal_projections:
        payload["goals"] = goal_projections

    if required_for_combined is not None and available_margin > 0:
        payload["combined_scenario"] = _combined_scenario(
            required=required_for_combined,
            margin=available_margin,
            rate=rate,
            basis=basis,
            horizons=horizons,
        )

    return payload


class FinancialInsightContextBuilder:
    """Build sanitized financial snapshots for daily, weekly and monthly insights."""

    def build_daily(
        self,
        *,
        user_id: UUID,
        anchor_date: date,
        previous_generated_at: datetime | None = None,
        timezone_name: str = _TIMEZONE,
        timezone_fallback: bool = False,
    ) -> dict[str, Any]:
        """Return a daily snapshot with extended temporal comparisons."""
        current = self._period_snapshot(
            user_id=user_id,
            start=anchor_date,
            end=anchor_date,
            label=anchor_date.isoformat(),
            period_type="daily",
            include_budgets=True,
            include_goals=True,
            include_credit_cards=True,
            include_wallet=True,
            previous_generated_at=previous_generated_at,
            timezone_name=timezone_name,
            timezone_fallback=timezone_fallback,
        )
        yesterday = anchor_date - timedelta(days=1)
        previous_week = anchor_date - timedelta(days=7)
        same_day_previous_month = _same_day_previous_month(anchor_date)
        same_day_previous_year = _same_day_previous_year(anchor_date)
        month_start = date(anchor_date.year, anchor_date.month, 1)
        week_start, _ = _week_bounds(anchor_date)
        week_elapsed_days = (anchor_date - week_start).days
        previous_week_start = week_start - timedelta(days=7)
        previous_week_equivalent_end = previous_week_start + timedelta(
            days=week_elapsed_days
        )
        week_to_date = self._period_snapshot(
            user_id=user_id,
            start=week_start,
            end=anchor_date,
            label=f"{anchor_date.isocalendar().year}-W{anchor_date.isocalendar().week:02d}-to-date",
            period_type="week_to_date",
        )
        previous_week_to_date = self._period_snapshot(
            user_id=user_id,
            start=previous_week_start,
            end=previous_week_equivalent_end,
            label=(
                f"{previous_week_start.isocalendar().year}-"
                f"W{previous_week_start.isocalendar().week:02d}-equivalent"
            ),
            period_type="previous_week_to_date",
        )

        missing_comparisons: list[str] = []
        comparisons: dict[str, Any] = {
            "yesterday": self._comparison_snapshot(
                user_id=user_id,
                current=current,
                start=yesterday,
                end=yesterday,
                label=yesterday.isoformat(),
            ),
            "previous_week": self._comparison_snapshot(
                user_id=user_id,
                current=current,
                start=previous_week,
                end=previous_week,
                label=previous_week.isoformat(),
            ),
            "month_to_date": self._compact_period_snapshot(
                self._period_snapshot(
                    user_id=user_id,
                    start=month_start,
                    end=anchor_date,
                    label=f"{anchor_date:%Y-%m}-to-{anchor_date:%d}",
                    period_type="month_to_date",
                )
            ),
            "week_to_date_vs_previous_week": {
                "current": self._compact_period_snapshot(week_to_date),
                "previous": self._compact_period_snapshot(previous_week_to_date),
                "delta": self._delta(
                    week_to_date["current_period"],
                    previous_week_to_date,
                ),
            },
        }
        if same_day_previous_month is not None:
            comparisons["same_day_previous_month"] = self._comparison_snapshot(
                user_id=user_id,
                current=current,
                start=same_day_previous_month,
                end=same_day_previous_month,
                label=same_day_previous_month.isoformat(),
            )
        else:
            missing_comparisons.append("same_day_previous_month")

        if same_day_previous_year is not None:
            comparisons["same_day_previous_year"] = self._comparison_snapshot(
                user_id=user_id,
                current=current,
                start=same_day_previous_year,
                end=same_day_previous_year,
                label=same_day_previous_year.isoformat(),
            )
        else:
            missing_comparisons.append("same_day_previous_year")

        current["comparisons"] = comparisons
        current["data_quality"]["missing_comparison_periods"] = missing_comparisons
        paid_balance = _money(
            ((current.get("current_period") or {}).get("paid") or {}).get("balance")
        )
        current["projections"] = _compute_projections(
            wallet=current.get("wallet") or {},
            goals=current.get("goals") or [],
            available_margin=max(paid_balance, Decimal(0)),
        )
        return current

    def build_weekly(
        self,
        *,
        user_id: UUID,
        anchor_date: date,
        previous_generated_at: datetime | None = None,
        timezone_name: str = _TIMEZONE,
        timezone_fallback: bool = False,
    ) -> dict[str, Any]:
        """Return a weekly snapshot for the ISO week containing ``anchor_date``."""
        start, end = _week_bounds(anchor_date)
        current = self._period_snapshot(
            user_id=user_id,
            start=start,
            end=end,
            label=f"{anchor_date.isocalendar().year}-W{anchor_date.isocalendar().week:02d}",
            period_type="weekly",
            include_daily_series=True,
            include_goals=True,
            include_credit_cards=True,
            include_wallet=True,
            previous_generated_at=previous_generated_at,
            timezone_name=timezone_name,
            timezone_fallback=timezone_fallback,
        )
        previous_start = start - timedelta(days=7)
        previous_end = start - timedelta(days=1)
        current["comparisons"] = {
            "previous_period": self._comparison_snapshot(
                user_id=user_id,
                current=current,
                start=previous_start,
                end=previous_end,
                label=(
                    f"{previous_start.isocalendar().year}-"
                    f"W{previous_start.isocalendar().week:02d}"
                ),
            )
        }
        return current

    def build_monthly(
        self,
        *,
        user_id: UUID,
        anchor_date: date,
        previous_generated_at: datetime | None = None,
        timezone_name: str = _TIMEZONE,
        timezone_fallback: bool = False,
    ) -> dict[str, Any]:
        """Return a monthly snapshot for the calendar month containing anchor."""
        start, end = _month_bounds(anchor_date)
        return self._period_snapshot(
            user_id=user_id,
            start=start,
            end=end,
            label=f"{anchor_date:%Y-%m}",
            period_type="monthly",
            include_daily_series=True,
            include_budgets=True,
            include_goals=True,
            include_credit_cards=True,
            include_wallet=True,
            previous_generated_at=previous_generated_at,
            timezone_name=timezone_name,
            timezone_fallback=timezone_fallback,
        )

    def _comparison_snapshot(
        self,
        *,
        user_id: UUID,
        current: dict[str, Any],
        start: date,
        end: date,
        label: str,
    ) -> dict[str, Any]:
        comparison = self._period_snapshot(
            user_id=user_id,
            start=start,
            end=end,
            label=label,
            period_type="comparison",
        )
        compact = self._compact_period_snapshot(comparison)
        compact["delta"] = self._delta(current["current_period"], comparison)
        return compact

    def _compact_period_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        current_period = snapshot["current_period"]
        return {
            "period": snapshot["period"],
            "paid": current_period["paid"],
            "commitments": current_period["commitments"],
            "cancelled_transaction_count": current_period[
                "cancelled_transaction_count"
            ],
            "transaction_count": snapshot["transactions"]["included_count"],
            "data_quality": snapshot["data_quality"],
        }

    def _period_snapshot(
        self,
        *,
        user_id: UUID,
        start: date,
        end: date,
        label: str,
        period_type: str,
        include_daily_series: bool = False,
        include_budgets: bool = False,
        include_goals: bool = False,
        include_credit_cards: bool = False,
        include_wallet: bool = False,
        market_rates: MarketRatesProvider | None = None,
        previous_generated_at: datetime | None = None,
        timezone_name: str = _TIMEZONE,
        timezone_fallback: bool = False,
    ) -> dict[str, Any]:
        due_transactions = self._fetch_transactions(
            user_id=user_id,
            start=start,
            end=end,
        )
        created_transactions = self._fetch_transactions_created(
            user_id=user_id,
            start=start,
            end=end,
        )
        transactions = self._merge_transactions(
            due_transactions,
            created_transactions,
        )
        non_cancelled = [
            tx for tx in transactions if tx.status != TransactionStatus.CANCELLED
        ]
        due_non_cancelled = [
            tx for tx in due_transactions if tx.status != TransactionStatus.CANCELLED
        ]
        paid = [tx for tx in due_non_cancelled if tx.status == TransactionStatus.PAID]

        current_period = self._current_period_summary(
            due_transactions,
            created_transactions=created_transactions,
        )
        goals_payload: list[dict[str, Any]] = []
        goal_data_quality: dict[str, Any] = {}
        if include_goals:
            goals_payload, goal_data_quality = self._goals_payload(
                user_id=user_id,
                anchor=end,
            )
        snapshot: dict[str, Any] = {
            "schema_version": _SNAPSHOT_VERSION,
            "period_type": period_type,
            "currency": _CURRENCY,
            "timezone": timezone_name,
            "anchor_date": end.isoformat(),
            "period": _date_period(start, end, label),
            "insight_contract": _insight_contract(),
            "current_period": current_period,
            "comparisons": {},
            "daily_series": self._daily_series(paid, start=start, end=end)
            if include_daily_series
            else [],
            "extremes": self._day_extremes(paid, start=start, end=end),
            "categories": {
                "top_expense_categories": self._top_expense_categories(paid)
            },
            "transactions": self._transactions_payload(
                non_cancelled,
                previous_generated_at=previous_generated_at,
            ),
            "budgets": self._budgets_payload(user_id=user_id, start=start, end=end)
            if include_budgets
            else [],
            "goals": goals_payload,
            "credit_cards": self._credit_cards_payload(user_id=user_id, anchor=end)
            if include_credit_cards
            else [],
            "data_quality": {
                "has_transactions": bool(non_cancelled),
                "missing_comparison_periods": [],
            },
        }
        if timezone_fallback:
            snapshot["data_quality"]["timezone_fallback"] = True
        snapshot["data_quality"].update(goal_data_quality)
        if include_wallet:
            wallet_payload, missing_rates = self._wallet_payload(
                user_id=user_id,
                anchor=end,
                market_rates=market_rates or get_default_market_rates_provider(),
            )
            snapshot["wallet"] = wallet_payload
            if missing_rates:
                snapshot["data_quality"]["missing_external_rates"] = missing_rates
        else:
            snapshot["wallet"] = {"items": [], "total_value": "0.00"}
        self._record_domain_presence(snapshot)
        snapshot["financial_health"] = self._financial_health_payload(snapshot)
        snapshot["data_quality"]["insufficient_financial_health_data"] = (
            snapshot["financial_health"]["grade"] == "insufficient_data"
        )
        return snapshot

    def _record_domain_presence(self, snapshot: dict[str, Any]) -> None:
        wallet = (
            snapshot.get("wallet") if isinstance(snapshot.get("wallet"), dict) else {}
        )
        wallet_items = wallet.get("items") if isinstance(wallet, dict) else []
        domain_presence = {
            "general": True,
            "transactions": bool(
                (snapshot.get("transactions") or {}).get("included_count")
            ),
            "credit_cards": bool(snapshot.get("credit_cards")),
            "goals": bool(snapshot.get("goals")),
            "budgets": bool(snapshot.get("budgets")),
            "wallet": bool(wallet_items) or _money(wallet.get("total_value")) > 0
            if isinstance(wallet, dict)
            else False,
        }
        snapshot["data_quality"]["domain_presence"] = domain_presence
        snapshot["data_quality"]["missing_domains"] = [
            dimension
            for dimension in INSIGHT_DIMENSIONS
            if not domain_presence.get(dimension, False)
        ]

    def _credit_cards_payload(
        self,
        *,
        user_id: UUID,
        anchor: date,
    ) -> list[dict[str, Any]]:
        """Sanitized list of cards with current-cycle utilization snapshot.

        Returns one entry per card belonging to the user. Cards without
        closing_day/due_day are skipped (utilization undefined). PII is
        never emitted — raw user IDs and external IDs stay out of the snapshot.
        """
        cards = (
            CreditCard.query.filter_by(user_id=user_id).order_by(CreditCard.name).all()
        )
        payload: list[dict[str, Any]] = []
        for card in cards:
            if card.closing_day is None or card.due_day is None:
                continue
            util = compute_utilization(card, today=anchor)
            payload.append(
                {
                    "name": _sanitize_text(card.name, max_length=60) or "Cartão",
                    "brand": _sanitize_text(card.brand, max_length=20) or None,
                    "bank": _sanitize_text(card.bank, max_length=60) or None,
                    "limit_amount": _money_str(util.limit_amount or 0)
                    if util.limit_amount is not None
                    else None,
                    "committed_amount": _money_str(util.committed_amount),
                    "available_amount": _money_str(util.available_amount or 0)
                    if util.available_amount is not None
                    else None,
                    "utilization_pct": util.utilization_pct,
                    "cycle": {
                        "start_date": util.cycle.start_date.isoformat(),
                        "end_date": util.cycle.end_date.isoformat(),
                        "due_date": util.cycle.due_date.isoformat(),
                        "status": util.cycle.status,
                    },
                }
            )
        return payload

    def _wallet_payload(
        self,
        *,
        user_id: UUID,
        anchor: date,
        market_rates: MarketRatesProvider,
    ) -> tuple[dict[str, Any], list[str]]:
        """Return (wallet_section, missing_external_rates).

        Sanitized list of holdings + asset-class distribution + investor
        profile diagnosis + benchmark CDI/IPCA for the anchor's month.
        """
        wallets = Wallet.query.filter_by(user_id=user_id).order_by(Wallet.name).all()
        user = User.query.filter_by(id=user_id).first()
        items = [self._serialize_wallet_item(w) for w in wallets]
        diagnosis = evaluate_allocation(
            investor_profile=getattr(user, "investor_profile", None) if user else None,
            wallets=wallets,
        )
        benchmark, missing = self._fetch_wallet_benchmark(
            market_rates=market_rates,
            year=anchor.year,
            month=anchor.month,
        )
        return (
            {
                "items": items,
                "total_value": _money_str(diagnosis.distribution.total_value),
                "distribution": {
                    "fixed_income_pct": _percent_str(
                        diagnosis.distribution.fixed_income_pct
                    ),
                    "market_pct": _percent_str(diagnosis.distribution.market_pct),
                    "custom_pct": _percent_str(diagnosis.distribution.custom_pct),
                },
                "profile_alignment": self._serialize_diagnosis(diagnosis),
                "benchmark": benchmark,
            },
            missing,
        )

    def _serialize_wallet_item(self, wallet: Wallet) -> dict[str, Any]:
        return {
            "name": _sanitize_text(wallet.name, max_length=80) or "Investimento",
            "asset_class": (wallet.asset_class or "custom").lower(),
            "current_value": _money_str(wallet.value or 0),
            "annual_rate": _percent_str(wallet.annual_rate or 0)
            if wallet.annual_rate is not None
            else None,
            "ticker": _sanitize_text(wallet.ticker, max_length=16)
            if wallet.ticker
            else None,
            "should_be_on_wallet": bool(wallet.should_be_on_wallet),
        }

    def _serialize_diagnosis(self, diagnosis: AllocationDiagnosis) -> dict[str, Any]:
        return {
            "profile": diagnosis.profile,
            "target_fixed_income_pct": _percent_str(
                diagnosis.target.target_fixed_income_pct
            )
            if diagnosis.target
            else None,
            "target_market_pct": _percent_str(diagnosis.target.target_market_pct)
            if diagnosis.target
            else None,
            "alert_level": diagnosis.alert_level,
            "drift_pp": _percent_str(diagnosis.drift_pp)
            if diagnosis.drift_pp is not None
            else None,
            "notes": list(diagnosis.notes),
        }

    def _fetch_wallet_benchmark(
        self,
        *,
        market_rates: MarketRatesProvider,
        year: int,
        month: int,
    ) -> tuple[dict[str, Any], list[str]]:
        cdi = market_rates.cdi_monthly(year=year, month=month)
        ipca = market_rates.ipca_monthly(year=year, month=month)
        missing: list[str] = []
        if cdi is None:
            missing.append("cdi_monthly")
        if ipca is None:
            missing.append("ipca_monthly")
        return (
            {
                "cdi_monthly_pct": _percent_str(cdi) if cdi is not None else None,
                "ipca_monthly_pct": _percent_str(ipca) if ipca is not None else None,
                "reference_year": year,
                "reference_month": month,
            },
            missing,
        )

    def _fetch_transactions(
        self,
        *,
        user_id: UUID,
        start: date,
        end: date,
    ) -> list[Transaction]:
        rows = (
            Transaction.query.filter(
                Transaction.user_id == user_id,
                Transaction.deleted.is_(False),
                Transaction.due_date >= start,
                Transaction.due_date <= end,
            )
            .order_by(Transaction.due_date.asc(), Transaction.created_at.asc())
            .all()
        )
        return cast(list[Transaction], rows)

    def _fetch_transactions_created(
        self,
        *,
        user_id: UUID,
        start: date,
        end: date,
    ) -> list[Transaction]:
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())
        rows = (
            Transaction.query.filter(
                Transaction.user_id == user_id,
                Transaction.deleted.is_(False),
                Transaction.created_at >= start_dt,
                Transaction.created_at < end_dt,
            )
            .order_by(Transaction.created_at.asc(), Transaction.due_date.asc())
            .all()
        )
        return cast(list[Transaction], rows)

    def _merge_transactions(
        self,
        *transaction_groups: list[Transaction],
    ) -> list[Transaction]:
        by_id: dict[UUID, Transaction] = {}
        for group in transaction_groups:
            for transaction in group:
                by_id[transaction.id] = transaction
        return sorted(
            by_id.values(),
            key=lambda tx: (tx.due_date, tx.created_at, _money(tx.amount)),
        )

    def _current_period_summary(
        self,
        transactions: list[Transaction],
        *,
        created_transactions: list[Transaction] | None = None,
    ) -> dict[str, Any]:
        paid = [tx for tx in transactions if tx.status == TransactionStatus.PAID]
        pending = [tx for tx in transactions if tx.status == TransactionStatus.PENDING]
        overdue = [tx for tx in transactions if tx.status == TransactionStatus.OVERDUE]
        cancelled_count = sum(
            1 for tx in transactions if tx.status == TransactionStatus.CANCELLED
        )
        created = [
            tx
            for tx in (created_transactions or [])
            if tx.status != TransactionStatus.CANCELLED
        ]
        created_pending = [
            tx
            for tx in created
            if tx.status in {TransactionStatus.PENDING, TransactionStatus.OVERDUE}
        ]

        paid_income = self._sum(paid, TransactionType.INCOME)
        paid_expense = self._sum(paid, TransactionType.EXPENSE)
        pending_expense = self._sum(pending, TransactionType.EXPENSE)
        overdue_expense = self._sum(overdue, TransactionType.EXPENSE)
        created_income = self._sum(created, TransactionType.INCOME)
        created_expense = self._sum(created, TransactionType.EXPENSE)
        created_pending_expense = self._sum(
            created_pending,
            TransactionType.EXPENSE,
        )

        return {
            "paid": {
                "income_total": _money_str(paid_income),
                "expense_total": _money_str(paid_expense),
                "balance": _money_str(paid_income - paid_expense),
                "transaction_count": len(paid),
            },
            "commitments": {
                "pending_expense_total": _money_str(pending_expense),
                "overdue_expense_total": _money_str(overdue_expense),
                "transaction_count": len(pending) + len(overdue),
            },
            "created_today": {
                "income_total": _money_str(created_income),
                "expense_total": _money_str(created_expense),
                "pending_expense_total": _money_str(created_pending_expense),
                "transaction_count": len(created),
                "items": self._transaction_event_payload(created)["items"],
            },
            "cancelled_transaction_count": cancelled_count,
        }

    def _delta(
        self,
        current_period: dict[str, Any],
        comparison_snapshot: dict[str, Any],
    ) -> dict[str, str]:
        current_paid = current_period["paid"]
        comparison_paid = comparison_snapshot["current_period"]["paid"]
        income_delta = _money(current_paid["income_total"]) - _money(
            comparison_paid["income_total"]
        )
        expense_delta = _money(current_paid["expense_total"]) - _money(
            comparison_paid["expense_total"]
        )
        balance_delta = _money(current_paid["balance"]) - _money(
            comparison_paid["balance"]
        )

        return {
            "income_total": _money_str(income_delta),
            "income_pct": _safe_pct(
                income_delta, _money(comparison_paid["income_total"])
            ),
            "expense_total": _money_str(expense_delta),
            "expense_pct": _safe_pct(
                expense_delta,
                _money(comparison_paid["expense_total"]),
            ),
            "balance": _money_str(balance_delta),
            "balance_pct": _safe_pct(
                balance_delta,
                _money(comparison_paid["balance"]),
            ),
        }

    def _daily_series(
        self,
        transactions: list[Transaction],
        *,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        index: dict[date, dict[str, Decimal | int]] = {}
        cursor = start
        while cursor <= end:
            index[cursor] = {
                "income": Decimal("0.00"),
                "expense": Decimal("0.00"),
                "count": 0,
            }
            cursor += timedelta(days=1)

        for tx in transactions:
            day = cast(date, tx.due_date)
            entry = index.setdefault(
                day,
                {"income": Decimal("0.00"), "expense": Decimal("0.00"), "count": 0},
            )
            if tx.type == TransactionType.INCOME:
                entry["income"] = cast(Decimal, entry["income"]) + _money(tx.amount)
            elif tx.type == TransactionType.EXPENSE:
                entry["expense"] = cast(Decimal, entry["expense"]) + _money(tx.amount)
            entry["count"] = cast(int, entry["count"]) + 1

        series: list[dict[str, Any]] = []
        cursor = start
        while cursor <= end:
            entry = index[cursor]
            income = cast(Decimal, entry["income"])
            expense = cast(Decimal, entry["expense"])
            series.append(
                {
                    "date": cursor.isoformat(),
                    "income_total": _money_str(income),
                    "expense_total": _money_str(expense),
                    "balance": _money_str(income - expense),
                    "transaction_count": cast(int, entry["count"]),
                }
            )
            cursor += timedelta(days=1)
        return series

    def _day_extremes(
        self,
        transactions: list[Transaction],
        *,
        start: date,
        end: date,
    ) -> dict[str, dict[str, str] | None]:
        series = self._daily_series(transactions, start=start, end=end)
        expense_days = [
            (item["date"], _money(item["expense_total"]))
            for item in series
            if _money(item["expense_total"]) > 0
        ]
        income_days = [
            (item["date"], _money(item["income_total"]))
            for item in series
            if _money(item["income_total"]) > 0
        ]
        return {
            "max_expense_day": self._extreme_day(expense_days, highest=True),
            "min_expense_day_with_activity": self._extreme_day(
                expense_days,
                highest=False,
            ),
            "max_income_day": self._extreme_day(income_days, highest=True),
            "min_income_day_with_activity": self._extreme_day(
                income_days,
                highest=False,
            ),
        }

    def _extreme_day(
        self,
        days: list[tuple[str, Decimal]],
        *,
        highest: bool,
    ) -> dict[str, str] | None:
        if not days:
            return None
        day, amount = (
            max(days, key=lambda item: item[1])
            if highest
            else min(
                days,
                key=lambda item: item[1],
            )
        )
        return {"date": day, "amount": _money_str(amount)}

    def _top_expense_categories(
        self,
        transactions: list[Transaction],
    ) -> list[dict[str, str]]:
        totals: dict[str, Decimal] = {}
        for tx in transactions:
            if tx.type != TransactionType.EXPENSE or tx.category is None:
                continue
            category = _enum_value(tx.category)
            if category is None:
                continue
            totals[category] = totals.get(category, Decimal("0.00")) + _money(tx.amount)

        return [
            {"category": category, "total": _money_str(total)}
            for category, total in sorted(
                totals.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]

    def _transactions_payload(
        self,
        transactions: list[Transaction],
        *,
        sample_limit: int = 20,
        previous_generated_at: datetime | None = None,
    ) -> dict[str, Any]:
        sorted_transactions = sorted(
            transactions,
            key=lambda tx: (tx.due_date, _money(tx.amount)),
        )
        return {
            "included_count": len(transactions),
            "sample": [
                self._serialize_transaction(tx)
                for tx in sorted_transactions[:sample_limit]
            ],
            "changes_since_last_generation": self._transaction_changes_payload(
                transactions,
                previous_generated_at=previous_generated_at,
            ),
        }

    def _transaction_changes_payload(
        self,
        transactions: list[Transaction],
        *,
        previous_generated_at: datetime | None,
    ) -> dict[str, Any]:
        if previous_generated_at is None:
            return {
                "since": None,
                "has_changes": False,
                "created": self._transaction_event_payload([]),
                "updated": self._transaction_event_payload([]),
                "paid": self._transaction_event_payload([]),
            }

        since = _naive_utc(previous_generated_at)
        created = [tx for tx in transactions if _datetime_after(tx.created_at, since)]
        updated = [
            tx
            for tx in transactions
            if _datetime_after(tx.updated_at, since)
            and not _datetime_after(tx.created_at, since)
        ]
        paid = [tx for tx in transactions if _datetime_after(tx.paid_at, since)]
        return {
            "since": since.isoformat(),
            "has_changes": bool(created or updated or paid),
            "created": self._transaction_event_payload(created),
            "updated": self._transaction_event_payload(updated),
            "paid": self._transaction_event_payload(paid),
        }

    def _transaction_event_payload(
        self,
        transactions: list[Transaction],
        *,
        item_limit: int = 10,
    ) -> dict[str, Any]:
        sorted_transactions = sorted(
            transactions,
            key=lambda tx: (tx.due_date, _money(tx.amount), str(tx.title or "")),
        )
        return {
            "count": len(transactions),
            "income_total": _money_str(self._sum(transactions, TransactionType.INCOME)),
            "expense_total": _money_str(
                self._sum(transactions, TransactionType.EXPENSE)
            ),
            "items": [
                self._serialize_transaction(tx)
                for tx in sorted_transactions[:item_limit]
            ],
        }

    def _serialize_transaction(self, transaction: Transaction) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "date": transaction.due_date.isoformat(),
            "type": _enum_value(transaction.type),
            "status": _enum_value(transaction.status),
            "amount": _money_str(transaction.amount),
            "currency": transaction.currency or _CURRENCY,
            "title": _sanitize_text(transaction.title),
            "is_recurring": bool(transaction.is_recurring),
            "is_installment": bool(transaction.is_installment),
        }
        description = _sanitize_text(transaction.description)
        category = _enum_value(transaction.category)
        if description and description != payload["title"]:
            payload["description"] = description
        if category:
            payload["category"] = category
        return payload

    def _budgets_payload(
        self,
        *,
        user_id: UUID,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        rows = (
            Budget.query.filter(
                Budget.user_id == user_id,
                Budget.is_active.is_(True),
                Budget.period == "monthly",
            )
            .order_by(Budget.created_at.asc())
            .all()
        )
        budgets = cast(list[Budget], rows)
        paid = [
            tx
            for tx in self._fetch_transactions(user_id=user_id, start=start, end=end)
            if tx.status == TransactionStatus.PAID
            and tx.type == TransactionType.EXPENSE
        ]

        result: list[dict[str, Any]] = []
        for budget in budgets:
            category = str(budget.category) if budget.category else None
            spent = Decimal("0.00")
            for tx in paid:
                if category is None or _enum_value(tx.category) == category:
                    spent += _money(tx.amount)

            amount = _money(budget.amount)
            result.append(
                {
                    "name": _sanitize_text(budget.name) or "Orçamento",
                    "category": category,
                    "period": str(budget.period),
                    "amount": _money_str(amount),
                    "spent": _money_str(spent),
                    "utilization_pct": _safe_pct(spent, amount),
                    "exceeded": spent > amount,
                }
            )
        return result

    def _goals_payload(
        self,
        *,
        user_id: UUID,
        anchor: date,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = (
            Goal.query.filter(
                Goal.user_id == user_id,
                Goal.status == "active",
            )
            .order_by(Goal.priority.asc(), Goal.created_at.asc())
            .all()
        )
        goals = cast(list[Goal], rows)
        if not goals:
            return [], {
                "has_active_goals": False,
                "insufficient_goal_pace_data": False,
                "goal_pace_window_days": _GOAL_PACE_WINDOW_DAYS,
            }

        cutoff = datetime(
            anchor.year, anchor.month, anchor.day, 23, 59, 59
        ) - timedelta(days=_GOAL_PACE_WINDOW_DAYS)
        contributions = cast(
            list[GoalContribution],
            GoalContribution.query.filter(
                GoalContribution.user_id == user_id,
                GoalContribution.created_at >= cutoff,
            )
            .order_by(GoalContribution.created_at.asc())
            .all(),
        )
        recent_by_goal: dict[str, Decimal] = {}
        for contribution in contributions:
            goal_key = str(contribution.goal_id)
            recent_by_goal[goal_key] = recent_by_goal.get(
                goal_key, Decimal("0.00")
            ) + _money(contribution.amount)

        result: list[dict[str, Any]] = []
        goals_without_deadline = 0
        goals_without_observed_pace = 0
        for goal in goals:
            current = _money(goal.current_amount)
            target = _money(goal.target_amount)
            remaining = max(target - current, Decimal("0.00"))
            days_remaining: int | None = None
            required_monthly_pace: Decimal | None = None
            if goal.target_date is None:
                goals_without_deadline += 1
            else:
                days_remaining = max((goal.target_date - anchor).days, 0)
                months_remaining = max((days_remaining + 29) // 30, 1)
                required_monthly_pace = (
                    remaining / Decimal(months_remaining)
                    if remaining > 0
                    else Decimal("0.00")
                )

            recent_90d = max(
                recent_by_goal.get(str(goal.id), Decimal("0.00")),
                Decimal("0.00"),
            )
            observed_monthly_pace = recent_90d / (
                Decimal(_GOAL_PACE_WINDOW_DAYS) / Decimal(30)
            )
            if recent_90d == 0 and remaining > 0:
                goals_without_observed_pace += 1
            pace_assessment, pace_basis = _goal_pace_assessment(
                remaining=remaining,
                required_monthly_pace=required_monthly_pace,
                observed_monthly_pace=observed_monthly_pace,
                has_target_date=goal.target_date is not None,
                has_contribution_history=recent_90d > 0,
            )
            result.append(
                {
                    "title": _sanitize_text(goal.title) or "Meta",
                    "current_amount": _money_str(current),
                    "target_amount": _money_str(target),
                    "progress_pct": _safe_pct(current, target),
                    "target_date": goal.target_date.isoformat()
                    if goal.target_date
                    else None,
                    "remaining_amount": _money_str(remaining),
                    "days_remaining": days_remaining,
                    "required_monthly_pace": _money_str(required_monthly_pace)
                    if required_monthly_pace is not None
                    else None,
                    "observed_monthly_pace_90d": _money_str(observed_monthly_pace),
                    "pace_assessment": pace_assessment,
                    "pace_basis": pace_basis,
                }
            )
        return result, {
            "has_active_goals": True,
            "insufficient_goal_pace_data": any(
                goal.get("pace_assessment") == "insufficient_data" for goal in result
            ),
            "goals_without_deadline_count": goals_without_deadline,
            "goals_without_observed_pace_count": goals_without_observed_pace,
            "goal_pace_window_days": _GOAL_PACE_WINDOW_DAYS,
        }

    def _financial_health_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        data_quality = snapshot.get("data_quality") or {}
        has_transactions = bool(
            isinstance(data_quality, dict) and data_quality.get("has_transactions")
        )
        if not has_transactions:
            return {
                "score": 50,
                "grade": "insufficient_data",
                "risk_flags": [
                    _risk_flag(
                        code="insufficient_transaction_data",
                        severity="info",
                        dimension="general",
                        evidence=["data_quality.has_transactions"],
                    )
                ],
            }

        paid = snapshot["current_period"]["paid"]
        commitments = snapshot["current_period"]["commitments"]
        balance = _money(paid["balance"])
        income = _money(paid["income_total"])
        pending = _money(commitments["pending_expense_total"])
        overdue = _money(commitments["overdue_expense_total"])
        penalties = [
            *_transaction_risk_penalties(
                balance=balance,
                income=income,
                pending=pending,
                overdue=overdue,
            ),
            *_budget_risk_penalties(snapshot.get("budgets")),
            *_credit_card_risk_penalties(snapshot.get("credit_cards")),
            *_goal_risk_penalties(snapshot.get("goals")),
        ]
        risk_flags = [flag for _penalty, flag in penalties]
        score = 100 - sum(penalty for penalty, _flag in penalties)
        score = max(0, min(100, score))
        return {
            "score": score,
            "grade": _financial_health_grade(score),
            "risk_flags": risk_flags,
            "inputs": {
                "paid_balance": _money_str(balance),
                "paid_income_total": _money_str(income),
                "pending_expense_total": _money_str(pending),
                "overdue_expense_total": _money_str(overdue),
            },
        }

    def _sum(
        self,
        transactions: list[Transaction],
        transaction_type: TransactionType,
    ) -> Decimal:
        return sum(
            (_money(tx.amount) for tx in transactions if tx.type == transaction_type),
            Decimal("0.00"),
        )


def _measure_snapshot_bytes(snapshot: dict[str, Any]) -> int:
    """Return UTF-8 byte size of the JSON-serialized snapshot."""
    return len(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _trim_transactions(snapshot: dict[str, Any]) -> bool:
    txs = snapshot.get("transactions")
    if not isinstance(txs, dict):
        return False
    items = txs.get("items")
    if not (isinstance(items, list) and len(items) > 15):
        return False
    expenses = [i for i in items if i.get("type") == "expense"]
    incomes = [i for i in items if i.get("type") == "income"]
    kept = (
        sorted(expenses, key=lambda i: float(i.get("amount", 0) or 0), reverse=True)[
            :10
        ]
        + sorted(incomes, key=lambda i: float(i.get("amount", 0) or 0), reverse=True)[
            :5
        ]
    )
    snapshot["transactions"] = {**txs, "items": kept}
    return True


def _trim_daily_series(snapshot: dict[str, Any]) -> bool:
    series = snapshot.get("daily_series")
    if isinstance(series, list) and len(series) > 7:
        snapshot["daily_series"] = series[-7:]
        return True
    return False


def _trim_idle_credit_cards(snapshot: dict[str, Any]) -> bool:
    cards = snapshot.get("credit_cards")
    if not (isinstance(cards, list) and cards):
        return False
    active = [
        c
        for c in cards
        if isinstance(c, dict) and c.get("utilization_pct") not in (None, 0, 0.0)
    ]
    if len(active) < len(cards):
        snapshot["credit_cards"] = active
        return True
    return False


def _trim_top_categories(snapshot: dict[str, Any]) -> bool:
    categories = snapshot.get("categories")
    if not isinstance(categories, dict):
        return False
    top = categories.get("top_expense_categories")
    if isinstance(top, list) and len(top) > 5:
        snapshot["categories"] = {**categories, "top_expense_categories": top[:5]}
        return True
    return False


def _trim_wallet_items(snapshot: dict[str, Any]) -> bool:
    """Keep top 10 holdings by current_value; preserves distribution/benchmark."""
    wallet = snapshot.get("wallet")
    if not isinstance(wallet, dict):
        return False
    items = wallet.get("items")
    if not (isinstance(items, list) and len(items) > 10):
        return False

    def _sort_key(entry: dict[str, Any]) -> float:
        try:
            return float(entry.get("current_value", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    kept = sorted(items, key=_sort_key, reverse=True)[:10]
    snapshot["wallet"] = {**wallet, "items": kept}
    return True


def truncate_snapshot(
    snapshot: dict[str, Any],
    *,
    max_bytes: int = MAX_SNAPSHOT_BYTES,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(possibly_truncated, info)`` keeping the snapshot under max_bytes.

    Truncation order (least → most destructive):

    1. transactions: keep top 10 by expense amount, then top 5 income.
    2. daily_series: keep most recent 7 entries.
    3. credit_cards: drop entries with zero/None utilization_pct.
    4. categories.top_expense_categories: keep top 5.

    Always preserved: ``schema_version``, ``period_type``, ``period``,
    ``current_period``, ``comparisons``, ``data_quality``. Caller receives
    a dict describing what changed for observability.
    """
    original_bytes = _measure_snapshot_bytes(snapshot)
    info: dict[str, Any] = {
        "snapshot_bytes_original": original_bytes,
        "snapshot_bytes_final": original_bytes,
        "truncated": False,
        "dropped_sections": [],
        "max_bytes": max_bytes,
    }
    if original_bytes <= max_bytes:
        return snapshot, info

    truncated = dict(snapshot)
    dropped: list[str] = info["dropped_sections"]
    steps = (
        ("transactions.items", _trim_transactions),
        ("daily_series", _trim_daily_series),
        ("credit_cards.idle", _trim_idle_credit_cards),
        ("categories.top_expense_categories", _trim_top_categories),
        ("wallet.items", _trim_wallet_items),
    )
    for label, step in steps:
        if step(truncated):
            dropped.append(label)
        if _measure_snapshot_bytes(truncated) <= max_bytes:
            break

    final_bytes = _measure_snapshot_bytes(truncated)
    info["snapshot_bytes_final"] = final_bytes
    info["truncated"] = True
    _log.warning(
        "ai_advisory.snapshot.truncated original=%d final=%d dropped=%s",
        original_bytes,
        final_bytes,
        dropped,
    )
    return truncated, info


__all__ = [
    "FinancialInsightContextBuilder",
    "INSIGHT_DIMENSIONS",
    "MAX_SNAPSHOT_BYTES",
    "truncate_snapshot",
]
