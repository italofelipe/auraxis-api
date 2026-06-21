"""Tests for enrich_insight_payload — additive Fluida composition (#1501).

``enrich_insight_payload`` takes an existing insight payload dict (as returned by
``AIAdvisoryService.generate_financial_insights`` / ``get_ai_insight_by_id``) and
adds the structured Fluida fields WITHOUT removing or mutating prior keys.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.extensions.database import db
from app.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.services.insight_fluida_builder import enrich_insight_payload


def _make_user() -> uuid.UUID:
    user = User(
        name="Enrich Cliente",
        email=f"enrich-{uuid.uuid4().hex[:8]}@example.com",
        password="hashed",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _make_expense(user_id: uuid.UUID, *, amount: str, due_date: date) -> None:
    tx = Transaction(
        user_id=user_id,
        title="gasto",
        description="gasto",
        amount=Decimal(amount),
        type=TransactionType.EXPENSE,
        status=TransactionStatus.PAID,
        due_date=due_date,
    )
    db.session.add(tx)
    db.session.commit()


def _base_payload() -> dict[str, object]:
    return {
        "id": "abc",
        "period_type": "daily",
        "period_label": "2026-06-15",
        "period_start": "2026-06-15",
        "period_end": "2026-06-15",
        "summary": "Primeiro.\n\nSegundo.",
        "items": [{"type": "saude_financeira", "dimension": "general"}],
        "context_version": "financial_insight_snapshot.v1",
        "context_hash": "deadbeef",
        "tokens_used": 100,
        "cost_usd": 0.0001,
        "model": "gpt-4o-mini",
        "cached": False,
        "forecast": False,
    }


class TestEnrichInsightPayload:
    def test_adds_all_four_structured_fields(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            enriched = enrich_insight_payload(
                _base_payload(), user_id=user_id, anchor=date(2026, 6, 15)
            )
        assert "paragraphs" in enriched
        assert "retro" in enriched
        assert "series" in enriched
        assert "highlights" in enriched

    def test_preserves_all_existing_keys_unchanged(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            original = _base_payload()
            enriched = enrich_insight_payload(
                dict(original), user_id=user_id, anchor=date(2026, 6, 15)
            )
        for key, value in original.items():
            assert enriched[key] == value

    def test_paragraphs_derive_from_summary(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            enriched = enrich_insight_payload(
                _base_payload(), user_id=user_id, anchor=date(2026, 6, 15)
            )
        assert enriched["paragraphs"] == ["Primeiro.", "Segundo."]

    def test_series_has_seven_daily_six_weekly(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            enriched = enrich_insight_payload(
                _base_payload(), user_id=user_id, anchor=date(2026, 6, 15)
            )
        assert len(enriched["series"]["daily"]) == 7
        assert len(enriched["series"]["weekly"]) == 6

    def test_retro_reflects_calculated_outflow(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_expense(user_id, amount="42.00", due_date=date(2026, 6, 14))
            enriched = enrich_insight_payload(
                _base_payload(), user_id=user_id, anchor=date(2026, 6, 15)
            )
        retro = {e["key"]: e for e in enriched["retro"]}
        assert retro["yesterday"]["value"] == 42.0

    def test_anchor_defaults_to_period_start_when_omitted(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            # Expense on the day before period_start (2026-06-15) → "yesterday".
            _make_expense(user_id, amount="15.00", due_date=date(2026, 6, 14))
            enriched = enrich_insight_payload(_base_payload(), user_id=user_id)
        retro = {e["key"]: e for e in enriched["retro"]}
        assert retro["yesterday"]["value"] == 15.0

    def test_does_not_mutate_input_dict_in_place_for_existing_keys(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            original = _base_payload()
            enrich_insight_payload(original, user_id=user_id, anchor=date(2026, 6, 15))
        # The four new keys may be added, but original business keys keep value.
        assert original["summary"] == "Primeiro.\n\nSegundo."
        assert original["items"] == [
            {"type": "saude_financeira", "dimension": "general"}
        ]

    def test_falls_back_to_today_when_no_anchor_and_no_period_start(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            today = date.today()
            yesterday = today - timedelta(days=1)
            _make_expense(user_id, amount="17.00", due_date=yesterday)
            payload = _base_payload()
            payload.pop("period_start")
            enriched = enrich_insight_payload(payload, user_id=user_id)
        retro = {e["key"]: e for e in enriched["retro"]}
        assert retro["yesterday"]["value"] == 17.0
