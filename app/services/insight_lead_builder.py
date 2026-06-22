"""Deterministic editorial *lead* for the "Insights Fluida" screen (#1503).

The Fluida masthead renders an editorial **lead** above the body the previous
step (:mod:`app.services.insight_fluida_builder`) already produces. The lead has
five fields and NONE of them costs an extra LLM call:

``severity`` (``ok`` | ``attention`` | ``alert``)
    A **heuristic** over the deterministic numbers the builder already computed
    (week-over-week outflow variation + the biggest expense's share of the
    month) — never the LLM. See :func:`derive_severity`.

``read_min`` (int)
    A **fixed** reading-time table by cadence × scope. See
    :func:`resolve_read_min` — Daily: 15 (general) / 3 (theme); Weekly &
    Monthly: 30 (general) / 5 (theme).

``title`` / ``lead`` / ``next_step`` (str)
    **Derived deterministically from the AI ``summary``** the generation already
    produced — we do NOT add a second LLM round-trip nor change the existing
    prompt/response schema. Deriving (instead of re-prompting) is what keeps the
    fresh, cached *and* by-id paths consistent: all three only persist/replay the
    ``summary`` string, so a prompt-only field would be absent on cache hits and
    historic rows. See :func:`derive_title_and_lead` / :func:`derive_next_step`.

The contract mirrors the canonical mobile view-model
(``auraxis-app/features/insights/fluida/contracts.ts``): English ``severity``
enum (``ok``/``attention``/``alert``), ``title``, ``lead`` (opening paragraph)
and ``read_min``; snake_case to match the sibling Fluida fields
(``paragraphs``/``retro``/``series``/``highlights``).
"""

from __future__ import annotations

import re
from typing import Any, Literal, NamedTuple

Severity = Literal["ok", "attention", "alert"]


class WeekOverWeek(NamedTuple):
    """Current vs previous week outflow totals feeding the severity heuristic."""

    current: float
    previous: float


# --- severity heuristic thresholds (documented, testable) -------------------
# Weekly outflow variation, measured as (current_week - previous_week) /
# previous_week. Spending MORE than the prior week is the only direction that
# can raise severity; spending less is always favourable (``ok``).
_ALERT_WEEK_RATIO = 1.0  # +100% week-over-week or more → alert
_ATTENTION_WEEK_RATIO = 0.30  # +30%..+100% → attention
# Spend concentration: a single expense worth this share (or more) of the
# month's total outflow is a structural alert regardless of weekly variation.
_DOMINANT_SPEND_SHARE = 0.55

# --- read_min table ---------------------------------------------------------
# General is the cross-cutting masthead reading (long); themes are focused tabs
# (short). Monthly recaps reuse the weekly (deepest) reading times.
_READ_MIN: dict[str, dict[str, int]] = {
    "daily": {"general": 15, "theme": 3},
    "weekly": {"general": 30, "theme": 5},
}
_GENERAL_DIMENSION = "general"

# --- summary derivation -----------------------------------------------------
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# A trailing sentence that reads like a recommendation becomes ``next_step``.
_RECOMMENDATION_RE = re.compile(
    r"\b("
    r"recomend|priorize|priorizar|sugiro|sugest|consider|considere|"
    r"vale|evite|evitar|comece|construa|defina|revise|reveja|mantenha|"
    r"foque|foco|distribua|antecipe|quite|quitar|classifique|crie|"
    r"pr[oó]xim[oa]\s+(passo|semana|m[eê]s)|continue"
    r")",
    re.IGNORECASE,
)


def _sentences(summary: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(summary.strip()) if s.strip()]


def derive_severity(
    *,
    week_over_week: WeekOverWeek,
    dominant_spend_share: float = 0.0,
) -> Severity:
    """Heuristically classify the period's urgency from deterministic numbers.

    Rule (no AI):

    * ``alert`` when the weekly outflow rose by ``>= 100%`` versus the prior
      week, **or** the single biggest expense is ``>= 55%`` of the month's total
      outflow (``dominant_spend_share``, a concentrated/dominant spend).
    * ``attention`` when the weekly outflow rose by ``>= 30%`` (and ``< 100%``).
    * ``ok`` otherwise — including when spending fell or there is no prior-week
      baseline to compare against.
    """
    if dominant_spend_share >= _DOMINANT_SPEND_SHARE:
        return "alert"

    ratio = _weekly_increase_ratio(week_over_week)
    if ratio is None:
        return "ok"
    if ratio >= _ALERT_WEEK_RATIO:
        return "alert"
    if ratio >= _ATTENTION_WEEK_RATIO:
        return "attention"
    return "ok"


def _weekly_increase_ratio(week_over_week: WeekOverWeek) -> float | None:
    """Fractional week-over-week outflow increase, or ``None`` when not rising.

    Expressed as ``(current - previous) / previous``. Returns ``None`` when
    spending did not rise or there is no positive baseline to compare against
    (e.g. the user's first week ever).
    """
    current = float(week_over_week.current or 0.0)
    previous = float(week_over_week.previous or 0.0)
    if previous <= 0 or current <= previous:
        return None
    return (current - previous) / previous


def resolve_read_min(*, cadence: str, dimension: str) -> int:
    """Fixed reading-time (minutes) by cadence × scope (general vs theme)."""
    table = _READ_MIN.get(cadence.strip().lower(), _READ_MIN["weekly"])
    scope = "general" if dimension == _GENERAL_DIMENSION else "theme"
    return table[scope]


def derive_title_and_lead(summary: str | None) -> tuple[str, str]:
    """First sentence of the summary becomes the title; the whole summary is the
    opening ``lead`` paragraph. Empty/blank summaries yield empty strings."""
    if not summary or not summary.strip():
        return "", ""
    cleaned = summary.strip()
    sentences = _sentences(cleaned)
    title = sentences[0] if sentences else cleaned
    return title, cleaned


def derive_next_step(summary: str | None) -> str:
    """The recommendation to surface as "para onde seguir".

    Prefer the last sentence that reads like a recommendation; otherwise fall
    back to the final sentence of the summary. Empty when there is no summary.
    """
    if not summary or not summary.strip():
        return ""
    sentences = _sentences(summary)
    if not sentences:
        return ""
    for sentence in reversed(sentences):
        if _RECOMMENDATION_RE.search(sentence):
            return sentence
    return sentences[-1]


def build_lead(
    *,
    summary: str | None,
    cadence: str,
    dimension: str,
    week_over_week: WeekOverWeek,
    dominant_spend_share: float = 0.0,
) -> dict[str, Any]:
    """Compose the full editorial lead for one (dimension, cadence) reading."""
    title, lead_text = derive_title_and_lead(summary)
    return {
        "severity": derive_severity(
            week_over_week=week_over_week,
            dominant_spend_share=dominant_spend_share,
        ),
        "read_min": resolve_read_min(cadence=cadence, dimension=dimension),
        "title": title,
        "lead": lead_text,
        "next_step": derive_next_step(summary),
    }


__all__ = [
    "WeekOverWeek",
    "build_lead",
    "derive_next_step",
    "derive_severity",
    "derive_title_and_lead",
    "resolve_read_min",
]
