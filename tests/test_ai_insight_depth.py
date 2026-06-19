"""Deep reports + per-period max_tokens for AI insights (#1481).

The daily insight stays lean (~3 min reading); weekly/monthly are deep reports
(~15 min). The output token budget scales per period and a (advisory-only) depth
gate flags generations that fall short of the reading-time target.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from app.services.llm_provider import (
    LLMResponse,
    _resolve_max_tokens,
    _timeout_for_max_tokens,
)


def _financial_llm_response(*, summary: str = "Resumo.") -> LLMResponse:
    dims = [
        ("general", "current_period.paid.balance"),
        ("transactions", "transactions.included_count"),
        ("credit_cards", "data_quality.domain_presence.credit_cards"),
        ("goals", "data_quality.domain_presence.goals"),
        ("budgets", "data_quality.domain_presence.budgets"),
        ("wallet", "data_quality.domain_presence.wallet"),
    ]
    items = ",".join(
        (
            '{"type":"saude_financeira",'
            f'"dimension":"{d}","title":"Item",'
            '"message":"Os dados foram analisados.",'
            f'"evidence":["{e}"]}}'
        )
        for d, e in dims
    )
    return LLMResponse(
        content=f'{{"summary":"{summary}","items":[{items}]}}',
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        model="gpt-4o-mini",
        latency_ms=120,
    )


class TestDepthPrompt:
    def test_daily_prompt_targets_3_min_reading(self) -> None:
        from app.services.ai_advisory_service import _build_financial_insight_prompt

        prompt = _build_financial_insight_prompt(
            {"schema_version": "v1", "data_quality": {}, "insight_contract": {}},
            period_type="daily",
        )
        assert "3 minutos de leitura" in prompt

    def test_long_prompts_target_15_min_reading(self) -> None:
        from app.services.ai_advisory_service import _build_financial_insight_prompt

        for period in ("weekly", "monthly"):
            prompt = _build_financial_insight_prompt(
                {"schema_version": "v1", "data_quality": {}, "insight_contract": {}},
                period_type=period,
            )
            assert "15 minutos de leitura" in prompt


class TestPeriodMaxTokens:
    def test_daily_default_budget(self) -> None:
        from app.services.ai_advisory_service import _period_max_tokens

        assert _period_max_tokens("daily") == 1500

    def test_long_default_budget(self) -> None:
        from app.services.ai_advisory_service import _period_max_tokens

        assert _period_max_tokens("weekly") == 6000
        assert _period_max_tokens("monthly") == 6000

    def test_env_override(self) -> None:
        from app.services.ai_advisory_service import _period_max_tokens

        with patch.dict(
            "os.environ",
            {
                "AI_INSIGHT_MAX_TOKENS_DAILY": "999",
                "AI_INSIGHT_MAX_TOKENS_LONG": "8000",
            },
        ):
            assert _period_max_tokens("daily") == 999
            assert _period_max_tokens("monthly") == 8000

    def test_generate_passes_daily_budget_to_provider(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response()
            service = AIAdvisoryService(user_id=uuid.uuid4(), llm_provider=provider)
            service.generate_financial_insights(
                period_type="daily", anchor_date=date(2026, 5, 17)
            )
            assert provider.generate_with_usage.call_args.kwargs["max_tokens"] == 1500

    def test_generate_passes_long_budget_to_provider(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response()
            service = AIAdvisoryService(user_id=uuid.uuid4(), llm_provider=provider)
            service.generate_financial_insights(
                period_type="monthly", anchor_date=date(2026, 5, 17)
            )
            assert provider.generate_with_usage.call_args.kwargs["max_tokens"] == 6000


class TestDepthGate:
    def test_reading_word_count_sums_summary_and_items(self) -> None:
        from app.services.ai_advisory_service import _insight_reading_word_count

        count = _insight_reading_word_count(
            "um dois tres",
            [{"title": "quatro cinco", "message": "seis sete oito"}],
        )
        assert count == 8

    def test_below_target_records_metric(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            provider = MagicMock()
            # Short canned response → far below the daily 450-word target.
            provider.generate_with_usage.return_value = _financial_llm_response()
            service = AIAdvisoryService(user_id=uuid.uuid4(), llm_provider=provider)
            with patch(
                "app.services.ai_advisory_service.record_ai_insight_depth_below_target"
            ) as rec:
                service.generate_financial_insights(
                    period_type="daily", anchor_date=date(2026, 5, 17)
                )
            rec.assert_called_once()
            assert rec.call_args.kwargs["period_type"] == "daily"


class TestProviderMaxTokens:
    def test_resolve_max_tokens_explicit_and_default(self) -> None:
        assert _resolve_max_tokens(3000) == 3000
        assert _resolve_max_tokens(None) == 512
        with patch.dict("os.environ", {"AI_INSIGHT_MAX_TOKENS_DEFAULT": "777"}):
            assert _resolve_max_tokens(None) == 777

    def test_timeout_scales_with_budget(self) -> None:
        assert _timeout_for_max_tokens(512) == 20
        assert _timeout_for_max_tokens(1500) == 60
        assert _timeout_for_max_tokens(6000) == 120  # capped

    def test_openai_payload_uses_max_tokens_and_timeout(self) -> None:
        from app.services.llm_provider import OpenAILLMProvider

        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            provider = OpenAILLMProvider()

        fake = MagicMock()
        fake.raise_for_status.return_value = None
        fake.json.return_value = {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "model": "gpt-4o",
        }
        with patch("requests.post", return_value=fake) as post:
            provider.generate_with_usage("hi", max_tokens=6000)

        assert post.call_args.kwargs["json"]["max_tokens"] == 6000
        assert post.call_args.kwargs["timeout"] == 120
