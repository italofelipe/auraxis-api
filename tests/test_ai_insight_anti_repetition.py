"""Anti-repetition guarantees for the daily insight prompt (#1654).

The PO's requirement is blunt: *"Um insight diário nunca deve ser repetido,
mesmo que o usuário não tenha registrado receitas/despesas, metas, orçamentos e
gastos novos no cartão ou investimentos."*

The cache was never the culprit — ``_get_cached_insight_for_snapshot`` scopes by
``period_label``, so one day's text is never served on another. What repeated was
the *writing*, and these tests pin the three prompt-level defences.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.services.ai_advisory_service import (
    _build_financial_insight_prompt,
    _has_no_new_activity,
)
from app.services.insight_angle_rotation import resolve_daily_angle

_USER = UUID("33333333-3333-3333-3333-333333333333")

_BASE_SNAPSHOT = {
    "schema_version": "v3",
    "data_quality": {},
    "insight_contract": {},
}


def _prompt_for(
    day: date, *, snapshot: dict | None = None, titles: list[str] | None = None
) -> str:
    return _build_financial_insight_prompt(
        snapshot if snapshot is not None else dict(_BASE_SNAPSHOT),
        period_type="daily",
        angle=resolve_daily_angle(_USER, day),
        recent_titles=titles or [],
    )


class TestLensRotation:
    def test_consecutive_days_ask_for_different_lenses(self) -> None:
        """Same snapshot, different days — the instruction must not match."""
        first = _prompt_for(date(2026, 8, 1))
        second = _prompt_for(date(2026, 8, 2))

        assert "LENTE DE HOJE" in first
        assert "LENTE DE HOJE" in second
        assert first != second

    def test_the_lens_is_absent_for_non_daily_periods(self) -> None:
        """Weekly and monthly are already long-form; rotation is a daily device."""
        prompt = _build_financial_insight_prompt(
            dict(_BASE_SNAPSHOT), period_type="weekly"
        )

        assert "LENTE DE HOJE" not in prompt


class TestShortMemory:
    def test_recent_titles_are_injected_as_a_ban_list(self) -> None:
        prompt = _prompt_for(
            date(2026, 8, 1),
            titles=["O mês fecha no azul", "Assinaturas subiram"],
        )

        assert "TÍTULOS JÁ USADOS" in prompt
        assert "O mês fecha no azul" in prompt
        assert "PROIBIDO repetir" in prompt

    def test_the_ban_list_is_explicitly_not_a_source_of_facts(self) -> None:
        """Without this the model could cite yesterday's headline as data."""
        prompt = _prompt_for(date(2026, 8, 1), titles=["Sobra de R$ 2.000"])

        assert "não é fonte" in prompt

    def test_no_ban_list_section_when_there_is_no_history(self) -> None:
        prompt = _prompt_for(date(2026, 8, 1), titles=[])

        assert "TÍTULOS JÁ USADOS" not in prompt


class TestQuietDayMode:
    def test_detects_a_day_with_nothing_new(self) -> None:
        snapshot = {
            **_BASE_SNAPSHOT,
            "transactions": {"changes_since_last_generation": []},
            "current_period": {"created_today": {"transaction_count": 0}},
        }

        assert _has_no_new_activity(snapshot) is True

    def test_a_new_transaction_disables_the_mode(self) -> None:
        snapshot = {
            **_BASE_SNAPSHOT,
            "transactions": {"changes_since_last_generation": []},
            "current_period": {"created_today": {"transaction_count": 3}},
        }

        assert _has_no_new_activity(snapshot) is False

    def test_a_recorded_change_disables_the_mode(self) -> None:
        snapshot = {
            **_BASE_SNAPSHOT,
            "transactions": {"changes_since_last_generation": [{"id": "x"}]},
            "current_period": {"created_today": {"transaction_count": 0}},
        }

        assert _has_no_new_activity(snapshot) is False

    def test_quiet_day_prompt_demands_substance_instead_of_nothing_changed(
        self,
    ) -> None:
        """The whole point of the PO's request: a quiet day still owes a reading."""
        snapshot = {
            **_BASE_SNAPSHOT,
            "transactions": {"changes_since_last_generation": []},
            "current_period": {"created_today": {"transaction_count": 0}},
        }

        prompt = _prompt_for(date(2026, 8, 1), snapshot=snapshot)

        assert "MODO SEM MOVIMENTO" in prompt
        assert "NÃO se limite a dizer que nada mudou" in prompt
        # Every source it may draw on has to be a snapshot key the evidence
        # validator recognises, or the items get rejected downstream.
        for key in (
            "month_summary.burn_rate_daily",
            "goals",
            "budgets",
            "daily_series",
        ):
            assert key in prompt

    def test_busy_day_prompt_omits_the_quiet_mode(self) -> None:
        snapshot = {
            **_BASE_SNAPSHOT,
            "current_period": {"created_today": {"transaction_count": 2}},
        }

        prompt = _prompt_for(date(2026, 8, 1), snapshot=snapshot)

        assert "MODO SEM MOVIMENTO" not in prompt
