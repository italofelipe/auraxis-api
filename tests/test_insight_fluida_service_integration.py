"""Service-level wiring of Fluida fields into the insight payload (#1501).

Confirms ``AIAdvisoryService.generate_financial_insights`` and
``get_ai_insight_by_id`` expose the structured Fluida fields, and that NONE of
the pre-existing contract keys regress (backward compatibility).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from app.extensions.database import db
from app.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.services.ai_advisory_service import AIAdvisoryService
from app.services.ai_monthly_report_service import get_ai_insight_by_id
from app.services.llm_provider import LLMResponse

_LEGACY_FINANCIAL_KEYS = {
    "id",
    "period_type",
    "period_label",
    "period_start",
    "period_end",
    "summary",
    "items",
    "context_version",
    "context_hash",
    "tokens_used",
    "cost_usd",
    "model",
    "cached",
    "forecast",
}
_FLUIDA_KEYS = {"paragraphs", "retro", "series", "highlights"}


def _make_user() -> uuid.UUID:
    user = User(
        name="Svc Cliente",
        email=f"svc-{uuid.uuid4().hex[:8]}@example.com",
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


_SUMMARY = (
    "Você manteve as contas em dia este mês. "
    "O maior gasto continua sendo a moradia. "
    "Vale revisar os gastos com lazer na próxima semana."
)


def _financial_llm_response(summary: str = _SUMMARY) -> LLMResponse:
    item = (
        '{"type":"saude_financeira","dimension":"general","title":"Item",'
        '"message":"Os dados foram analisados.",'
        '"evidence":["current_period.paid.balance"]}'
    )
    return LLMResponse(
        content=f'{{"summary":"{summary}","items":[{item}]}}',
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        model="gpt-4o-mini",
        latency_ms=120,
    )


class TestGenerateFinancialInsightsEnriched:
    def test_fresh_payload_has_fluida_and_legacy_keys(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_expense(user_id, amount="42.00", due_date=date(2026, 6, 14))
            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response()
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)

            result = service.generate_financial_insights(
                period_type="daily", anchor_date=date(2026, 6, 15)
            )

        # No contract regression: every legacy key still present.
        assert _LEGACY_FINANCIAL_KEYS <= set(result)
        # New structured fields present.
        assert _FLUIDA_KEYS <= set(result)
        # Calculated outflow reflects the seeded transaction.
        retro = {e["key"]: e for e in result["retro"]}
        assert retro["yesterday"]["value"] == 42.0
        # Paragraphs derived from the AI summary (long block → sentences).
        assert result["paragraphs"] == [
            "Você manteve as contas em dia este mês.",
            "O maior gasto continua sendo a moradia.",
            "Vale revisar os gastos com lazer na próxima semana.",
        ]
        # Series anchored on period_start.
        assert len(result["series"]["daily"]) == 7
        assert result["series"]["daily"][-2] == 42.0

    def test_cached_payload_also_enriched(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_expense(user_id, amount="30.00", due_date=date(2026, 6, 14))
            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response()
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)

            first = service.generate_financial_insights(
                period_type="daily", anchor_date=date(2026, 6, 15)
            )
            assert first["cached"] is False

            # Second identical call hits the snapshot cache (no new LLM call).
            second = service.generate_financial_insights(
                period_type="daily", anchor_date=date(2026, 6, 15)
            )

        assert second["cached"] is True
        assert _FLUIDA_KEYS <= set(second)
        retro = {e["key"]: e for e in second["retro"]}
        assert retro["yesterday"]["value"] == 30.0


class TestGetAiInsightByIdEnriched:
    def test_detail_payload_has_fluida_and_legacy_keys(self, app) -> None:
        with app.app_context():
            user_id = _make_user()
            _make_expense(user_id, amount="55.00", due_date=date(2026, 6, 14))
            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response()
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            generated = service.generate_financial_insights(
                period_type="daily", anchor_date=date(2026, 6, 15)
            )
            insight_id = uuid.UUID(generated["id"])

            detail = get_ai_insight_by_id(user_id=user_id, insight_id=insight_id)

        # Legacy detail keys preserved.
        for key in (
            "id",
            "content",
            "summary",
            "items",
            "insight_type",
            "period_type",
            "period_label",
            "period_start",
            "period_end",
            "model",
            "tokens_used",
            "cost_usd",
            "created_at",
        ):
            assert key in detail
        # Fluida fields added.
        assert _FLUIDA_KEYS <= set(detail)
        retro = {e["key"]: e for e in detail["retro"]}
        assert retro["yesterday"]["value"] == 55.0
