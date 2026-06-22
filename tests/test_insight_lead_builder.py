"""Unit tests for the deterministic Fluida editorial lead (#1503).

The lead (``severity`` / ``read_min`` / ``title`` / ``lead`` / ``next_step``) is
derived WITHOUT any extra LLM call:

* ``severity`` is a heuristic over the deterministic ``retro`` block (weekly
  outflow variation) and ``highlights`` (spend concentration).
* ``read_min`` is a fixed table by cadence × scope (general vs theme).
* ``title`` / ``lead`` / ``next_step`` are derived from the AI ``summary`` that
  the generation already produced (first sentence → title, opening → lead, last
  recommendation-like sentence → next_step).

These cover every severity band, every read_min cell and the summary derivation.
"""

from __future__ import annotations

from app.services.insight_lead_builder import (
    WeekOverWeek,
    build_lead,
    derive_next_step,
    derive_severity,
    derive_title_and_lead,
    resolve_read_min,
)


def _wow(*, week_delta: float, prev_week: float = 100.0) -> WeekOverWeek:
    """Build a ``WeekOverWeek`` from a delta over a baseline."""
    return WeekOverWeek(current=prev_week + week_delta, previous=prev_week)


class TestDeriveSeverity:
    def test_alert_when_weekly_outflow_spikes_above_high_threshold(self) -> None:
        # +120% week-over-week → far above the alert band.
        wow = _wow(week_delta=120.0, prev_week=100.0)
        assert derive_severity(week_over_week=wow) == "alert"

    def test_alert_when_a_single_expense_dominates_the_month(self) -> None:
        # No weekly spike, but the biggest expense is >= 55% of month outflow.
        wow = _wow(week_delta=0.0, prev_week=100.0)
        assert derive_severity(week_over_week=wow, dominant_spend_share=0.55) == "alert"

    def test_attention_on_moderate_weekly_variation(self) -> None:
        # +40% week-over-week → moderate band.
        wow = _wow(week_delta=40.0, prev_week=100.0)
        assert derive_severity(week_over_week=wow) == "attention"

    def test_ok_when_variation_is_small_and_no_dominant_spend(self) -> None:
        wow = _wow(week_delta=5.0, prev_week=100.0)
        assert derive_severity(week_over_week=wow, dominant_spend_share=0.20) == "ok"

    def test_ok_when_spending_dropped(self) -> None:
        # Spending less than last week is favourable → never an alert/attention.
        wow = _wow(week_delta=-80.0, prev_week=100.0)
        assert derive_severity(week_over_week=wow) == "ok"

    def test_ok_when_there_is_no_prior_week_baseline(self) -> None:
        # First week ever: prev_week == 0 → no ratio, so no spike signal.
        wow = _wow(week_delta=500.0, prev_week=0.0)
        assert derive_severity(week_over_week=wow) == "ok"


class TestResolveReadMin:
    def test_daily_general(self) -> None:
        assert resolve_read_min(cadence="daily", dimension="general") == 15

    def test_daily_theme(self) -> None:
        assert resolve_read_min(cadence="daily", dimension="transactions") == 3

    def test_weekly_general(self) -> None:
        assert resolve_read_min(cadence="weekly", dimension="general") == 30

    def test_weekly_theme(self) -> None:
        assert resolve_read_min(cadence="weekly", dimension="goals") == 5

    def test_monthly_falls_back_to_weekly_table(self) -> None:
        # Monthly is a long recap → reuse the weekly (deepest) reading times.
        assert resolve_read_min(cadence="monthly", dimension="general") == 30
        assert resolve_read_min(cadence="monthly", dimension="budgets") == 5


class TestDeriveTitleAndLead:
    def test_first_sentence_becomes_title_rest_is_lead(self) -> None:
        summary = (
            "Você manteve as contas em dia. "
            "O maior gasto foi a moradia. "
            "Vale revisar o lazer."
        )
        title, lead = derive_title_and_lead(summary)
        assert title == "Você manteve as contas em dia."
        assert lead == summary

    def test_single_sentence_summary(self) -> None:
        title, lead = derive_title_and_lead("Tudo certo por aqui.")
        assert title == "Tudo certo por aqui."
        assert lead == "Tudo certo por aqui."

    def test_empty_summary_yields_empty_strings(self) -> None:
        assert derive_title_and_lead(None) == ("", "")
        assert derive_title_and_lead("   ") == ("", "")


class TestDeriveNextStep:
    def test_picks_last_recommendation_sentence(self) -> None:
        summary = "As contas seguem apertadas. Recomendo priorizar a fatura em atraso."
        assert derive_next_step(summary) == "Recomendo priorizar a fatura em atraso."

    def test_falls_back_to_last_sentence_when_no_keyword(self) -> None:
        summary = "Mês tranquilo. Saldo positivo no fim do período."
        assert derive_next_step(summary) == "Saldo positivo no fim do período."

    def test_empty_summary_yields_empty_string(self) -> None:
        assert derive_next_step(None) == ""
        assert derive_next_step("") == ""


class TestBuildLead:
    def test_general_daily_lead_shape(self) -> None:
        wow = _wow(week_delta=5.0, prev_week=100.0)
        summary = "Dia leve. Continue acompanhando os gastos."
        lead = build_lead(
            summary=summary,
            cadence="daily",
            dimension="general",
            week_over_week=wow,
        )
        assert lead == {
            "severity": "ok",
            "read_min": 15,
            "title": "Dia leve.",
            "lead": summary,
            "next_step": "Continue acompanhando os gastos.",
        }

    def test_alert_weekly_general_lead(self) -> None:
        wow = _wow(week_delta=200.0, prev_week=100.0)
        lead = build_lead(
            summary="Semana pesada. Quite a fatura com urgência.",
            cadence="weekly",
            dimension="general",
            week_over_week=wow,
        )
        assert lead["severity"] == "alert"
        assert lead["read_min"] == 30
        assert lead["next_step"] == "Quite a fatura com urgência."

    def test_theme_read_min_is_used_for_non_general_dimension(self) -> None:
        wow = _wow(week_delta=0.0, prev_week=100.0)
        lead = build_lead(
            summary="Resumo do tema.",
            cadence="daily",
            dimension="transactions",
            week_over_week=wow,
        )
        assert lead["read_min"] == 3
