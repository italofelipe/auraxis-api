"""Tests for AIAdvisoryService and AI advisory controller endpoints (#1206).

Coverage areas:
- LLMResponse dataclass and estimated_cost_usd property
- StubLLMProvider.generate_with_usage()
- AIAdvisoryService.generate_spending_insights()
- AIAdvisoryService.generate_goal_projection_narrative()
- AIAdvisoryService.generate_weekly_summary_narrative()
- LLMAuditLog persistence
- Entitlement gate (premium required)
- GET /ai/insights/spending — auth, entitlement, happy path
- POST /ai/goals/<goal_id>/projection — auth, entitlement, validation, happy path
- GET /ai/insights/weekly-summary — auth, entitlement, happy path
- LLMProviderError propagation
- Goal not found raises ValueError → 404
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm_provider import LLMProviderError, LLMResponse, StubLLMProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(client, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@test.com"
    password = "StrongPass@123"
    reg = client.post(
        "/auth/register",
        json={"name": f"{prefix}-{suffix}", "email": email, "password": password},
    )
    assert reg.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.get_json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _grant_entitlement(app, user_id: uuid.UUID, feature_key: str) -> None:
    """Grant an entitlement directly in the DB for test setup."""
    with app.app_context():
        from app.extensions.database import db
        from app.models.entitlement import Entitlement, EntitlementSource

        ent = Entitlement(
            user_id=user_id,
            feature_key=feature_key,
            source=EntitlementSource.MANUAL,
            expires_at=None,
        )
        db.session.add(ent)
        db.session.commit()


def _revoke_premium_entitlements(app, user_id: uuid.UUID) -> None:
    """Revoke all premium-only entitlements so user is effectively on free plan."""
    with app.app_context():
        from app.services.entitlement_service import deactivate_premium

        deactivate_premium(user_id)


def _get_current_user_id(app, token: str) -> uuid.UUID:
    """Extract user UUID from the JWT token."""
    with app.app_context():
        from flask_jwt_extended import decode_token

        decoded = decode_token(token)
        return uuid.UUID(decoded["sub"])


def _financial_llm_response(
    *,
    summary: str = "Resumo financeiro.",
) -> LLMResponse:
    items = [
        (
            "general",
            "current_period.paid.balance",
            "Panorama geral",
        ),
        (
            "transactions",
            "transactions.included_count",
            "Movimentações",
        ),
        (
            "credit_cards",
            "data_quality.domain_presence.credit_cards",
            "Cartões",
        ),
        (
            "goals",
            "data_quality.domain_presence.goals",
            "Metas",
        ),
        (
            "budgets",
            "data_quality.domain_presence.budgets",
            "Orçamentos",
        ),
        (
            "wallet",
            "data_quality.domain_presence.wallet",
            "Carteira",
        ),
    ]
    payload_items = ",".join(
        (
            '{"type":"saude_financeira",'
            f'"dimension":"{dimension}",'
            f'"title":"{title}",'
            '"message":"Os dados do domínio foram analisados.",'
            f'"evidence":["{evidence}"]}}'
        )
        for dimension, evidence, title in items
    )
    return LLMResponse(
        content=(f'{{"summary":"{summary}","items":[{payload_items}]}}'),
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        model="gpt-4o-mini",
        latency_ms=120,
    )


# ---------------------------------------------------------------------------
# LLMResponse tests
# ---------------------------------------------------------------------------


class TestLLMResponse:
    def test_known_model_cost(self) -> None:
        resp = LLMResponse(
            content="test",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            total_tokens=2_000_000,
            model="gpt-4o-mini",
            latency_ms=100,
        )
        # 1M prompt * 0.15 + 1M completion * 0.60 = 0.75
        assert abs(resp.estimated_cost_usd - 0.75) < 1e-6

    def test_unknown_model_fallback_cost(self) -> None:
        resp = LLMResponse(
            content="test",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            total_tokens=2_000_000,
            model="unknown-model",
            latency_ms=50,
        )
        # fallback: 0.002 + 0.008 = 0.010
        assert abs(resp.estimated_cost_usd - 0.010) < 1e-6

    def test_zero_tokens_zero_cost(self) -> None:
        resp = LLMResponse(
            content="",
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            model="gpt-4o-mini",
            latency_ms=0,
        )
        assert resp.estimated_cost_usd == 0.0

    def test_claude_model_cost(self) -> None:
        resp = LLMResponse(
            content="ok",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            total_tokens=2_000_000,
            model="claude-haiku-4-5-20251001",
            latency_ms=200,
        )
        # 1M * 0.25 + 1M * 1.25 = 1.50
        assert abs(resp.estimated_cost_usd - 1.50) < 1e-6


# ---------------------------------------------------------------------------
# StubLLMProvider tests
# ---------------------------------------------------------------------------


class TestStubLLMProvider:
    def test_generate_returns_string(self) -> None:
        provider = StubLLMProvider()
        result = provider.generate("any prompt")
        assert isinstance(result, str)
        assert len(result) > 10

    def test_generate_with_usage_returns_llm_response(self) -> None:
        provider = StubLLMProvider()
        result = provider.generate_with_usage("any prompt")
        assert isinstance(result, LLMResponse)
        assert result.content == provider.generate("any prompt")
        assert result.model == "stub"
        assert result.total_tokens > 0
        assert result.latency_ms == 0

    def test_generate_and_generate_with_usage_content_match(self) -> None:
        provider = StubLLMProvider()
        assert provider.generate("x") == provider.generate_with_usage("x").content


# ---------------------------------------------------------------------------
# AIAdvisoryService unit tests (mocked provider)
# ---------------------------------------------------------------------------


class TestAIAdvisoryServiceSpendingInsights:
    def test_generate_spending_insights_returns_expected_keys(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            provider = StubLLMProvider()
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            result = service.generate_spending_insights()
            assert "insights" in result
            assert "tokens_used" in result
            assert "cost_usd" in result
            assert "month" in result
            assert "model" in result

    def test_generate_spending_insights_with_explicit_month(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            provider = StubLLMProvider()
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            result = service.generate_spending_insights(month="2026-01")
            assert result["month"] == "2026-01"

    def test_generate_spending_insights_normalizes_fenced_json_and_returns_items(
        self, app
    ) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.return_value = LLMResponse(
                content=(
                    '```json\n[{"type":"saude_financeira","title":"Ok",'
                    '"message":"Tudo certo."}]\n```'
                ),
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                model="gpt-4o-mini",
                latency_ms=100,
            )

            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            result = service.generate_spending_insights(month="2026-05")

            assert result["items"] == [
                {
                    "type": "saude_financeira",
                    "title": "Ok",
                    "message": "Tudo certo.",
                }
            ]
            assert result["insights"] == (
                '[{"type":"saude_financeira","title":"Ok","message":"Tudo certo."}]'
            )
            assert "response_schema" in provider.generate_with_usage.call_args.kwargs

    def test_generate_spending_insights_rejects_malformed_provider_output(
        self, app
    ) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.return_value = LLMResponse(
                content="not-json",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                model="gpt-4o-mini",
                latency_ms=100,
            )

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)

            with pytest.raises(LLMProviderError, match="Invalid spending insight"):
                service.generate_spending_insights(month="2026-05")

            saved = db.session.query(AIInsight).filter_by(user_id=user_id).first()
            assert saved is None

    def test_llm_provider_error_propagates(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            broken = MagicMock()
            broken.generate_with_usage.side_effect = LLMProviderError("fail")

            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=broken)
            with pytest.raises(LLMProviderError):
                service.generate_spending_insights()


class TestAIAdvisoryServiceFinancialInsights:
    def test_generate_daily_financial_insights_returns_evidence_payload(
        self,
        app,
    ) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight, InsightType
            from app.models.llm_audit_log import LLMAuditLog
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response(
                summary="Resumo do dia."
            )

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            result = service.generate_financial_insights(
                period_type="daily",
                anchor_date=date(2026, 5, 17),
            )

            assert result["period_type"] == "daily"
            assert result["period_label"] == "2026-05-17"
            assert result["period_start"] == "2026-05-17"
            assert result["period_end"] == "2026-05-17"
            assert result["summary"] == "Resumo do dia."
            assert [item["dimension"] for item in result["items"]] == [
                "general",
                "transactions",
                "credit_cards",
                "goals",
                "budgets",
                "wallet",
            ]
            assert result["context_version"] == "financial_insight_snapshot.v1"
            assert result["cached"] is False
            assert result["tokens_used"] == 140

            call = provider.generate_with_usage.call_args
            prompt = call.args[0]
            assert "financial_insight_snapshot.v1" in prompt
            assert "Não invente transações" in prompt
            assert (
                call.kwargs["response_schema"]["name"] == "financial_insight_response"
            )

            saved = db.session.query(AIInsight).filter_by(user_id=user_id).one()
            assert result["id"] == str(saved.id)
            assert saved.insight_type == InsightType.daily
            assert saved.period_label == "2026-05-17"
            assert "current_period.paid.balance" in saved.content
            assert "context_hash" in saved.content

            audit = (
                db.session.query(LLMAuditLog)
                .filter_by(user_id=user_id, endpoint="financial_insights_daily")
                .one()
            )
            assert audit.model == "gpt-4o-mini"
            assert audit.total_tokens == 140

    def test_build_prompt_instructs_transactions_narrative_with_projections(
        self,
    ) -> None:
        from app.services.ai_advisory_service import _build_financial_insight_prompt

        prompt = _build_financial_insight_prompt(
            {"schema_version": "financial_insight_snapshot.v1"},
            period_type="daily",
        )
        assert "NARRATIVA" in prompt
        assert "projections" in prompt
        assert "comparisons.same_day_previous_month" in prompt
        assert "transactions.sample" in prompt

    def test_build_prompt_forecast_mode_frames_as_preview(self) -> None:
        from app.services.ai_advisory_service import _build_financial_insight_prompt

        snapshot = {"schema_version": "financial_insight_snapshot.v1"}
        forecast_prompt = _build_financial_insight_prompt(
            snapshot, period_type="monthly", forecast=True
        )
        normal_prompt = _build_financial_insight_prompt(
            snapshot, period_type="monthly", forecast=False
        )

        assert "MODO PREVISÃO" in forecast_prompt
        assert "MODO PREVISÃO" not in normal_prompt
        assert "panorama geral do mês" in normal_prompt

    def test_generate_financial_insights_flags_future_month_as_forecast(
        self,
        app,
    ) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response(
                summary="Prévia de julho."
            )
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)

            with patch(
                "app.services.ai_advisory_service.timezone_utils.local_today",
                return_value=date(2026, 5, 30),
            ):
                future = service.generate_financial_insights(
                    period_type="monthly",
                    anchor_date=date(2026, 7, 15),
                )
                current = service.generate_financial_insights(
                    period_type="monthly",
                    anchor_date=date(2026, 5, 15),
                )

            assert future["forecast"] is True
            assert current["forecast"] is False
            # Future-month generation must frame the prompt as a forecast.
            future_prompt = provider.generate_with_usage.call_args_list[0].args[0]
            assert "MODO PREVISÃO" in future_prompt

    def test_financial_insights_tolerate_missing_required_dimensions(
        self,
        app,
        caplog,
    ) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.return_value = LLMResponse(
                content=(
                    '{"summary":"Resumo incompleto.",'
                    '"items":[{"type":"saude_financeira",'
                    '"dimension":"general",'
                    '"title":"Só geral",'
                    '"message":"Apenas o panorama geral foi retornado.",'
                    '"evidence":["current_period.paid.balance"]}]}'
                ),
                prompt_tokens=100,
                completion_tokens=40,
                total_tokens=140,
                model="gpt-4o-mini",
                latency_ms=120,
            )

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            # Cobertura incompleta de dimensões NÃO deve derrubar a geração
            # (incidente 2026-06-01): degrada com aviso e persiste o insight
            # com as dimensões que o modelo retornou.
            with caplog.at_level(logging.WARNING):
                result = service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=date(2026, 5, 17),
                )

            assert result["items"][0]["dimension"] == "general"
            assert "dimension_coverage_incomplete" in caplog.text
            assert "credit_cards" in caplog.text

            saved = db.session.query(AIInsight).filter_by(user_id=user_id).first()
            assert saved is not None

    def test_financial_insights_prompt_uses_structured_deltas_not_previous_text(
        self,
        app,
    ) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight, InsightType
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            previous = AIInsight(
                user_id=user_id,
                content=(
                    "Insight antigo contaminado: meta do carro estourou por "
                    "R$ 999.999,00."
                ),
                insight_type=InsightType.daily,
                period_label="2026-05-16",
                period_start=date(2026, 5, 16),
                period_end=date(2026, 5, 16),
                model="gpt-4o-mini",
                tokens_used=100,
                cost_usd=0.000015,
                created_at=datetime(2026, 5, 16, 12, 0, 0),
            )
            db.session.add(previous)
            db.session.commit()

            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response(
                summary="Resumo sem contaminação."
            )

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            service.generate_financial_insights(
                period_type="daily",
                anchor_date=date(2026, 5, 17),
            )

            prompt = provider.generate_with_usage.call_args.args[0]
            assert "changes_since_last_generation" in prompt
            assert '"dimension"' in prompt
            assert "Insight antigo contaminado" not in prompt
            assert "R$ 999.999,00" not in prompt

    def test_financial_insights_return_cached_period_without_provider_call(
        self,
        app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response(
                summary="Resumo cache."
            )

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            first = service.generate_financial_insights(
                period_type="daily",
                anchor_date=date(2026, 5, 17),
            )
            monkeypatch.setenv("AI_INSIGHTS_DAILY_BUDGET_USD", "0.000001")
            second = service.generate_financial_insights(
                period_type="daily",
                anchor_date=date(2026, 5, 17),
            )

            assert first["cached"] is False
            assert second["cached"] is True
            assert second["summary"] == "Resumo cache."
            provider.generate_with_usage.assert_called_once()

    def test_financial_insights_regenerate_when_snapshot_hash_changes(
        self,
        app,
    ) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.side_effect = [
                _financial_llm_response(summary="Resumo inicial."),
                _financial_llm_response(summary="Resumo atualizado."),
            ]
            first_snapshot = {
                "schema_version": "financial_insight_snapshot.v1",
                "period_type": "daily",
                "period": {
                    "label": "2026-05-17",
                    "start": "2026-05-17",
                    "end": "2026-05-17",
                },
                "current_period": {
                    "paid": {
                        "income_total": "1000.00",
                        "expense_total": "250.00",
                        "balance": "750.00",
                        "transaction_count": 2,
                    },
                    "commitments": {
                        "pending_expense_total": "0.00",
                        "overdue_expense_total": "0.00",
                        "transaction_count": 0,
                    },
                    "cancelled_transaction_count": 0,
                },
                "comparisons": {},
                "transactions": {"included_count": 2, "sample": []},
                "data_quality": {
                    "has_transactions": True,
                    "missing_comparison_periods": [],
                },
            }
            changed_snapshot = {
                **first_snapshot,
                "current_period": {
                    **first_snapshot["current_period"],
                    "paid": {
                        **first_snapshot["current_period"]["paid"],
                        "balance": "700.00",
                    },
                },
            }

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            with patch(
                "app.services.ai_advisory_service._build_period_snapshot",
                side_effect=[first_snapshot, changed_snapshot],
            ):
                first = service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=date(2026, 5, 17),
                )
                second = service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=date(2026, 5, 17),
                )

            assert first["cached"] is False
            assert second["cached"] is False
            assert second["summary"] == "Resumo atualizado."
            assert first["context_hash"] != second["context_hash"]
            assert provider.generate_with_usage.call_count == 2

    def test_financial_insights_daily_budget_blocks_before_provider_call(
        self,
        app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.llm_audit_log import LLMAuditLog
            from app.services.ai_advisory_service import (
                AIAdvisoryService,
                AIInsightCostBudgetExceededError,
            )

            user_id = uuid.uuid4()
            db.session.add(
                LLMAuditLog(
                    user_id=user_id,
                    endpoint="financial_insights_daily",
                    model="gpt-4o-mini",
                    prompt="redacted",
                    response_text="redacted",
                    prompt_tokens=10,
                    completion_tokens=10,
                    total_tokens=20,
                    estimated_cost_usd=Decimal("0.01000000"),
                    latency_ms=50,
                )
            )
            db.session.commit()
            monkeypatch.setenv("AI_INSIGHTS_DAILY_BUDGET_USD", "0.01")
            monkeypatch.delenv("AI_INSIGHTS_MONTHLY_BUDGET_USD", raising=False)
            provider = MagicMock()

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            with pytest.raises(
                AIInsightCostBudgetExceededError,
                match="Orçamento diário de AI Insights atingido",
            ):
                service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=date(2026, 5, 17),
                )

            provider.generate_with_usage.assert_not_called()

    def test_financial_insights_monthly_budget_blocks_before_provider_call(
        self,
        app,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.llm_audit_log import LLMAuditLog
            from app.services.ai_advisory_service import (
                AIAdvisoryService,
                AIInsightCostBudgetExceededError,
            )

            user_id = uuid.uuid4()
            db.session.add(
                LLMAuditLog(
                    user_id=user_id,
                    endpoint="financial_insights_weekly",
                    model="gpt-4o-mini",
                    prompt="redacted",
                    response_text="redacted",
                    prompt_tokens=10,
                    completion_tokens=10,
                    total_tokens=20,
                    estimated_cost_usd=Decimal("0.02000000"),
                    latency_ms=50,
                )
            )
            db.session.commit()
            monkeypatch.delenv("AI_INSIGHTS_DAILY_BUDGET_USD", raising=False)
            monkeypatch.setenv("AI_INSIGHTS_MONTHLY_BUDGET_USD", "0.02")
            provider = MagicMock()

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            with pytest.raises(
                AIInsightCostBudgetExceededError,
                match="Orçamento mensal de AI Insights atingido",
            ):
                service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=date(2026, 5, 17),
                )

            provider.generate_with_usage.assert_not_called()

    def test_financial_insights_reject_invalid_payload_without_saving(
        self,
        app,
    ) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.return_value = LLMResponse(
                content='{"summary":"Resumo","items":[{"type":"saude_financeira"}]}',
                prompt_tokens=100,
                completion_tokens=40,
                total_tokens=140,
                model="gpt-4o-mini",
                latency_ms=120,
            )

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            with pytest.raises(LLMProviderError, match="Invalid financial insight"):
                service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=date(2026, 5, 17),
                )

            saved = db.session.query(AIInsight).filter_by(user_id=user_id).first()
            assert saved is None

    @pytest.mark.parametrize(
        ("period_type", "period_label", "period_start", "period_end"),
        [
            ("weekly", "2026-W20", "2026-05-11", "2026-05-17"),
            ("monthly", "2026-05", "2026-05-01", "2026-05-31"),
        ],
    )
    def test_generate_financial_insights_supports_weekly_and_monthly_periods(
        self,
        app,
        period_type: str,
        period_label: str,
        period_start: str,
        period_end: str,
    ) -> None:
        with app.app_context():
            from app.models.ai_insight import AIInsight, InsightType
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response()

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            result = service.generate_financial_insights(
                period_type=period_type,
                anchor_date=date(2026, 5, 17),
            )

            assert result["period_type"] == period_type
            assert result["period_label"] == period_label
            assert result["period_start"] == period_start
            assert result["period_end"] == period_end

            saved = AIInsight.query.filter_by(user_id=user_id).one()
            assert saved.insight_type == InsightType(period_type)
            assert saved.period_label == period_label

    def test_generate_financial_insights_can_reuse_preview_run_snapshot(
        self,
        app,
    ) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight, InsightType
            from app.models.ai_insight_run import AIInsightRunStatus
            from app.models.user import User
            from app.services.ai_advisory_service import AIAdvisoryService
            from app.services.ai_insight_runs import create_ai_insight_run

            user_id = uuid.uuid4()
            db.session.add(
                User(
                    id=user_id,
                    name="Preview User",
                    email=f"preview-{user_id.hex[:8]}@test.com",
                    password="x",
                )
            )
            db.session.commit()

            snapshot = {
                "schema_version": "financial_insight_snapshot.v1",
                "period_type": "daily",
                "period": {
                    "label": "2026-05-17",
                    "start": "2026-05-17",
                    "end": "2026-05-17",
                },
                "current_period": {
                    "paid": {
                        "income_total": "1000.00",
                        "expense_total": "250.00",
                        "balance": "750.00",
                        "transaction_count": 2,
                    },
                    "commitments": {
                        "pending_expense_total": "0.00",
                        "overdue_expense_total": "0.00",
                        "transaction_count": 0,
                    },
                    "cancelled_transaction_count": 0,
                },
                "comparisons": {},
                "transactions": {"included_count": 2, "sample": []},
                "data_quality": {
                    "has_transactions": True,
                    "missing_comparison_periods": [],
                },
            }
            preview_run = create_ai_insight_run(
                user_id=user_id,
                status=AIInsightRunStatus.previewed,
                period_type=InsightType.daily,
                period_label="2026-05-17",
                period_start=date(2026, 5, 17),
                period_end=date(2026, 5, 17),
                snapshot_schema_version="financial_insight_snapshot.v1",
                snapshot_hash="preview-hash-123",
                prompt_template_version="financial-insight.v1.preview",
                snapshot_json=snapshot,
                evidence_manifest_json={"items": []},
                data_quality_json=snapshot["data_quality"],
            )

            provider = MagicMock()
            provider.generate_with_usage.return_value = _financial_llm_response(
                summary="Resumo a partir do preview."
            )

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            with patch(
                "app.services.ai_advisory_service._build_period_snapshot",
                side_effect=AssertionError("snapshot should come from preview run"),
            ):
                result = service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=date(2026, 5, 17),
                    preview_run_id=preview_run.id,
                )

            assert result["context_hash"] == "preview-hash-123"
            assert result["cached"] is False
            saved = AIInsight.query.filter_by(user_id=user_id).one()
            db.session.refresh(preview_run)
            assert preview_run.status == AIInsightRunStatus.generated
            assert preview_run.ai_insight_id == saved.id
            assert preview_run.snapshot_hash == "preview-hash-123"
            assert preview_run.tokens_total == 140

    def test_audit_log_created_on_success(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            provider = StubLLMProvider()
            from app.models.llm_audit_log import LLMAuditLog
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            service.generate_spending_insights()

            log_row = LLMAuditLog.query.filter_by(
                user_id=user_id, endpoint="spending_insights"
            ).first()
            assert log_row is not None
            assert log_row.model == "stub"
            assert log_row.total_tokens > 0


class TestAIAdvisoryServiceGoalProjection:
    def _create_goal(self, app, user_id: uuid.UUID) -> uuid.UUID:
        with app.app_context():
            from app.extensions.database import db
            from app.models.goal import Goal

            goal = Goal(
                user_id=user_id,
                title="Viagem Europa",
                target_amount=Decimal("15000.00"),
                current_amount=Decimal("3000.00"),
                status="active",
            )
            db.session.add(goal)
            db.session.commit()
            return goal.id  # type: ignore[return-value]

    def test_goal_not_found_raises_value_error(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            provider = StubLLMProvider()
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            with pytest.raises(ValueError, match="not found"):
                service.generate_goal_projection_narrative(
                    goal_id=uuid.uuid4(),
                    user_context="Quero viajar",
                    monthly_contribution=Decimal("500"),
                )

    def test_goal_wrong_user_raises_value_error(self, app) -> None:
        with app.app_context():
            owner_id = uuid.uuid4()
            other_id = uuid.uuid4()
            goal_id = self._create_goal(app, owner_id)

            provider = StubLLMProvider()
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=other_id, llm_provider=provider)
            with pytest.raises(ValueError, match="not found"):
                service.generate_goal_projection_narrative(
                    goal_id=goal_id,
                    user_context="teste",
                    monthly_contribution=Decimal("500"),
                )

    def test_happy_path_returns_required_keys(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            goal_id = self._create_goal(app, user_id)
            provider = StubLLMProvider()
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            result = service.generate_goal_projection_narrative(
                goal_id=goal_id,
                user_context="Quero viajar para Europa em 2028",
                monthly_contribution=Decimal("500"),
            )
            assert "narrative" in result
            assert "tokens_used" in result
            assert "cost_usd" in result
            assert "projection" in result
            assert "model" in result
            assert isinstance(result["projection"], dict)


class TestAIAdvisoryServiceWeeklySummary:
    def test_weekly_summary_returns_required_keys(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            provider = StubLLMProvider()
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            result = service.generate_weekly_summary_narrative()
            assert "narrative" in result
            assert "tokens_used" in result
            assert "cost_usd" in result
            assert "summary" in result
            assert "model" in result

    def test_llm_error_propagates_in_weekly_summary(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            broken = MagicMock()
            broken.generate_with_usage.side_effect = LLMProviderError("fail")

            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=broken)
            with pytest.raises(LLMProviderError):
                service.generate_weekly_summary_narrative()

    def test_read_weekly_summary_without_insight_returns_empty_narrative(
        self, app
    ) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            # A broken provider proves the read path never touches the LLM.
            broken = MagicMock()
            broken.generate_with_usage.side_effect = LLMProviderError("must not call")

            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=broken)
            result = service.read_weekly_summary_narrative()

            assert result["narrative"] == ""
            assert result["generated_at"] is None
            assert "current_week" in result["summary"]
            broken.generate_with_usage.assert_not_called()

    def test_read_weekly_summary_returns_latest_persisted_narrative(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight, InsightType
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            iso = date.today().isocalendar()
            db.session.add(
                AIInsight(
                    user_id=user_id,
                    content='{"summary":"Resumo da semana.","items":[]}',
                    insight_type=InsightType.weekly,
                    period_label=f"{iso.year}-W{iso.week:02d}",
                    period_start=date.today(),
                    period_end=date.today(),
                    model="gpt-4o-mini",
                    tokens_used=99,
                    cost_usd=0,
                )
            )
            db.session.commit()

            service = AIAdvisoryService(user_id=user_id, llm_provider=MagicMock())
            result = service.read_weekly_summary_narrative()

            assert result["narrative"] == "Resumo da semana."
            assert result["model"] == "gpt-4o-mini"
            assert result["tokens_used"] == 99
            assert result["generated_at"] is not None


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


class TestAISpendingInsightsEndpoint:
    def test_unauthenticated_returns_401(self, client) -> None:
        resp = client.get("/ai/insights/spending")
        assert resp.status_code == 401

    def test_authenticated_free_user_returns_403(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-free")
        user_id = _get_current_user_id(app, token)
        # New registrations may get a trial; revoke premium to simulate free plan.
        _revoke_premium_entitlements(app, user_id)
        resp = client.get("/ai/insights/spending", headers=_auth(token))
        assert resp.status_code == 403

    def test_premium_user_returns_200(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-prem")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        resp = client.get("/ai/insights/spending", headers=_auth(token))
        assert resp.status_code == 200

    def test_response_has_required_keys(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-keys")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        resp = client.get("/ai/insights/spending", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data") or body
        for key in ("insights", "tokens_used", "cost_usd", "month", "model"):
            assert key in data, f"Missing key: {key}"

    def test_month_param_accepted(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-month")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        resp = client.get("/ai/insights/spending?month=2026-01", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data") or body
        assert data["month"] == "2026-01"

    def test_llm_error_returns_500(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-err")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_spending_insights",
            side_effect=LLMProviderError("provider down"),
        ):
            resp = client.get("/ai/insights/spending", headers=_auth(token))
            assert resp.status_code == 500


class TestAIInsightGenerateEndpoint:
    def test_post_invalid_period_type_returns_400(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-generate-invalid")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights"
        ) as mocked_generate:
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "yearly"},
                headers=_auth(token),
            )

        assert resp.status_code == 400
        mocked_generate.assert_not_called()

    def test_post_invalid_anchor_date_returns_400(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-generate-bad-date")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights"
        ) as mocked_generate:
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily", "anchor_date": "17/05/2026"},
                headers=_auth(token),
            )

        assert resp.status_code == 400
        mocked_generate.assert_not_called()

    def test_post_daily_generation_returns_period_payload(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-generate-daily")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        generated = {
            "period_type": "daily",
            "period_label": "2026-05-17",
            "period_start": "2026-05-17",
            "period_end": "2026-05-17",
            "summary": "Resumo do dia.",
            "items": [
                {
                    "type": "saude_financeira",
                    "title": "Dia equilibrado",
                    "message": "Receitas e despesas foram analisadas.",
                    "evidence": ["current_period.paid.balance"],
                }
            ],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "stub",
            "tokens_used": 123,
            "cost_usd": 0.00001,
        }

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights",
            return_value=generated,
        ) as mocked_generate:
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily", "anchor_date": "2026-05-17"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data") or body
        assert data == generated
        mocked_generate.assert_called_once()
        assert mocked_generate.call_args.kwargs == {
            "period_type": "daily",
            "anchor_date": date(2026, 5, 17),
            "preview_run_id": None,
        }

    def test_post_generation_uses_user_timezone_when_anchor_is_omitted(
        self,
        app,
        client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        token = _register_and_login(client, prefix="ai-generate-tz")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        generated = {
            "period_type": "daily",
            "period_label": "2026-05-21",
            "period_start": "2026-05-21",
            "period_end": "2026-05-21",
            "summary": "Resumo do dia local.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "stub",
            "tokens_used": 123,
            "cost_usd": 0.00001,
        }
        monkeypatch.setattr(
            "app.controllers.ai.resources.timezone_utils.utc_now",
            lambda: datetime(2026, 5, 22, 2, 30, tzinfo=timezone.utc),
        )

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights",
            return_value=generated,
        ) as mocked_generate:
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily"},
                headers={
                    **_auth(token),
                    "X-Auraxis-Timezone": "America/Sao_Paulo",
                },
            )

        assert resp.status_code == 200
        mocked_generate.assert_called_once()
        assert mocked_generate.call_args.kwargs == {
            "period_type": "daily",
            "anchor_date": date(2026, 5, 21),
            "preview_run_id": None,
            "timezone_name": "America/Sao_Paulo",
            "timezone_fallback": False,
        }

    def test_post_generation_falls_back_when_timezone_is_invalid(
        self,
        app,
        client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        token = _register_and_login(client, prefix="ai-generate-bad-tz")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        generated = {
            "period_type": "daily",
            "period_label": "2026-05-21",
            "period_start": "2026-05-21",
            "period_end": "2026-05-21",
            "summary": "Resumo com fallback.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "stub",
            "tokens_used": 123,
            "cost_usd": 0.00001,
        }
        monkeypatch.setattr(
            "app.controllers.ai.resources.timezone_utils.utc_now",
            lambda: datetime(2026, 5, 22, 2, 30, tzinfo=timezone.utc),
        )

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights",
            return_value=generated,
        ) as mocked_generate:
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily"},
                headers={
                    **_auth(token),
                    "X-Auraxis-Timezone": "Mars/Olympus_Mons",
                },
            )

        assert resp.status_code == 200
        mocked_generate.assert_called_once()
        assert mocked_generate.call_args.kwargs == {
            "period_type": "daily",
            "anchor_date": date(2026, 5, 21),
            "preview_run_id": None,
            "timezone_name": "America/Sao_Paulo",
            "timezone_fallback": True,
        }

    def test_post_generation_accepts_timezone_from_payload_when_header_is_absent(
        self,
        app,
        client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        token = _register_and_login(client, prefix="ai-generate-body-tz")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        generated = {
            "period_type": "daily",
            "period_label": "2026-05-21",
            "period_start": "2026-05-21",
            "period_end": "2026-05-21",
            "summary": "Resumo com timezone no payload.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "stub",
            "tokens_used": 123,
            "cost_usd": 0.00001,
        }
        monkeypatch.setattr(
            "app.controllers.ai.resources.timezone_utils.utc_now",
            lambda: datetime(2026, 5, 21, 23, 30, tzinfo=timezone.utc),
        )

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights",
            return_value=generated,
        ) as mocked_generate:
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily", "timezone": "Pacific/Kiritimati"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        mocked_generate.assert_called_once()
        assert mocked_generate.call_args.kwargs == {
            "period_type": "daily",
            "anchor_date": date(2026, 5, 22),
            "preview_run_id": None,
            "timezone_name": "Pacific/Kiritimati",
            "timezone_fallback": False,
        }

    def test_post_generation_accepts_preview_run_id(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-generate-preview")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")
        preview_run_id = uuid.uuid4()

        generated = {
            "period_type": "daily",
            "period_label": "2026-05-17",
            "period_start": "2026-05-17",
            "period_end": "2026-05-17",
            "summary": "Resumo do preview.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "context_hash": "preview-hash-123",
            "cached": False,
            "model": "stub",
            "tokens_used": 123,
            "cost_usd": 0.00001,
        }

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights",
            return_value=generated,
        ) as mocked_generate:
            resp = client.post(
                "/ai/insights/generate",
                json={
                    "period_type": "daily",
                    "anchor_date": "2026-05-17",
                    "preview_run_id": str(preview_run_id),
                },
                headers=_auth(token),
            )

        assert resp.status_code == 200
        mocked_generate.assert_called_once()
        assert mocked_generate.call_args.kwargs == {
            "period_type": "daily",
            "anchor_date": date(2026, 5, 17),
            "preview_run_id": preview_run_id,
        }

    def test_post_generation_budget_exceeded_returns_429(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-generate-budget")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        from app.services.ai_advisory_service import AIInsightCostBudgetExceededError

        error = AIInsightCostBudgetExceededError(
            "Orçamento diário de AI Insights atingido.",
            scope="daily",
            limit_usd=Decimal("0.01"),
            spent_usd=Decimal("0.01"),
        )

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights",
            side_effect=error,
        ):
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily", "anchor_date": "2026-05-17"},
                headers=_auth(token),
            )

        assert resp.status_code == 429
        body = resp.get_json()
        assert body["error"] == "Orçamento diário de AI Insights atingido."


class TestAIGoalProjectionEndpoint:
    def _create_goal_via_api(self, client, token: str) -> str:
        resp = client.post(
            "/goals",
            json={
                "title": "Meta Teste",
                "target_amount": 10000,
                "current_amount": 1000,
                "status": "active",
            },
            headers=_auth(token),
        )
        assert resp.status_code in (200, 201)
        data = resp.get_json()
        # Extract goal id from response
        goal_data = data.get("data", {}).get("goal") or data.get("goal") or {}
        return goal_data.get("id", "")

    def test_unauthenticated_returns_401(self, client) -> None:
        resp = client.post(
            f"/ai/goals/{uuid.uuid4()}/projection",
            json={"monthly_contribution": 500, "user_context": "teste"},
        )
        assert resp.status_code == 401

    def test_free_user_returns_403(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-gfree")
        user_id = _get_current_user_id(app, token)
        _revoke_premium_entitlements(app, user_id)
        goal_id = str(uuid.uuid4())
        resp = client.post(
            f"/ai/goals/{goal_id}/projection",
            json={"monthly_contribution": 500, "user_context": "teste"},
            headers=_auth(token),
        )
        assert resp.status_code == 403

    def test_invalid_goal_id_returns_400(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-gbad")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        resp = client.post(
            "/ai/goals/not-a-uuid/projection",
            json={"monthly_contribution": 500, "user_context": "teste"},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_missing_monthly_contribution_returns_400(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-gnomc")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        resp = client.post(
            f"/ai/goals/{uuid.uuid4()}/projection",
            json={"user_context": "teste"},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_goal_not_found_returns_404(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-g404")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        resp = client.post(
            f"/ai/goals/{uuid.uuid4()}/projection",
            json={"monthly_contribution": 500, "user_context": "teste"},
            headers=_auth(token),
        )
        assert resp.status_code == 404

    def test_happy_path_returns_200_with_narrative(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-gok")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        # Create goal directly in DB
        with app.app_context():
            from app.extensions.database import db
            from app.models.goal import Goal

            goal = Goal(
                user_id=user_id,
                title="Carro Novo",
                target_amount=Decimal("50000"),
                current_amount=Decimal("5000"),
                status="active",
            )
            db.session.add(goal)
            db.session.commit()
            goal_id = str(goal.id)

        resp = client.post(
            f"/ai/goals/{goal_id}/projection",
            json={
                "monthly_contribution": 1000,
                "user_context": "Quero comprar um carro",
            },
            headers=_auth(token),
        )
        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data") or body
        assert "narrative" in data
        assert "projection" in data


class TestAIWeeklySummaryEndpoint:
    def test_unauthenticated_returns_401(self, client) -> None:
        resp = client.get("/ai/insights/weekly-summary")
        assert resp.status_code == 401

    def test_free_user_returns_403(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-wfree")
        user_id = _get_current_user_id(app, token)
        _revoke_premium_entitlements(app, user_id)
        resp = client.get("/ai/insights/weekly-summary", headers=_auth(token))
        assert resp.status_code == 403

    def test_premium_user_returns_200(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-wprem")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        resp = client.get("/ai/insights/weekly-summary", headers=_auth(token))
        assert resp.status_code == 200

    def test_response_has_required_keys(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-wkeys")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        resp = client.get("/ai/insights/weekly-summary", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data") or body
        for key in ("narrative", "tokens_used", "cost_usd", "summary", "model"):
            assert key in data, f"Missing key: {key}"

    def test_read_is_side_effect_free_no_llm_no_email(self, app, client) -> None:
        """The GET must never generate an insight nor send an email."""
        token = _register_and_login(client, prefix="ai-wnoside")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        with (
            patch(
                "app.services.ai_advisory_service.AIAdvisoryService."
                "generate_weekly_summary_narrative"
            ) as gen,
            patch(
                "app.services.analysis_ready_notification_service."
                "dispatch_analysis_ready_notification"
            ) as notify,
        ):
            resp = client.get("/ai/insights/weekly-summary", headers=_auth(token))

        assert resp.status_code == 200
        gen.assert_not_called()
        notify.assert_not_called()
        body = resp.get_json()
        data = body.get("data") or body
        # No insight generated yet → empty narrative, no generation timestamp.
        assert data["narrative"] == ""
        assert data["generated_at"] is None

    def test_read_returns_persisted_weekly_narrative(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-wpersist")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight, InsightType

            iso = date.today().isocalendar()
            db.session.add(
                AIInsight(
                    user_id=user_id,
                    content='{"summary":"Sua semana foi positiva.","items":[]}',
                    insight_type=InsightType.weekly,
                    period_label=f"{iso.year}-W{iso.week:02d}",
                    period_start=date.today(),
                    period_end=date.today(),
                    model="gpt-4o-mini",
                    tokens_used=120,
                    cost_usd=0,
                )
            )
            db.session.commit()

        resp = client.get("/ai/insights/weekly-summary", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data") or body
        assert data["narrative"] == "Sua semana foi positiva."
        assert data["model"] == "gpt-4o-mini"
        assert data["generated_at"] is not None

    def test_read_error_returns_500(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-werr")
        user_id = _get_current_user_id(app, token)
        _grant_entitlement(app, user_id, "advanced_simulations")

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService."
            "read_weekly_summary_narrative",
            side_effect=RuntimeError("db down"),
        ):
            resp = client.get("/ai/insights/weekly-summary", headers=_auth(token))
            assert resp.status_code == 500


# ---------------------------------------------------------------------------
# LLMAuditLog model tests
# ---------------------------------------------------------------------------


class TestLLMAuditLogModel:
    def test_audit_log_can_be_created_and_retrieved(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.llm_audit_log import LLMAuditLog

            user_id = uuid.uuid4()
            log_row = LLMAuditLog(
                user_id=user_id,
                endpoint="spending_insights",
                model="stub",
                prompt="test prompt",
                response_text="test response",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                estimated_cost_usd=0.0001,
                latency_ms=50,
            )
            db.session.add(log_row)
            db.session.commit()

            retrieved = LLMAuditLog.query.filter_by(user_id=user_id).first()
            assert retrieved is not None
            assert retrieved.endpoint == "spending_insights"
            assert retrieved.model == "stub"
            assert retrieved.total_tokens == 150

    def test_audit_log_repr(self, app) -> None:
        with app.app_context():
            from app.models.llm_audit_log import LLMAuditLog

            user_id = uuid.uuid4()
            log_row = LLMAuditLog(
                user_id=user_id,
                endpoint="weekly_summary",
                model="gpt-4o-mini",
                prompt="p",
                response_text="r",
                total_tokens=99,
            )
            r = repr(log_row)
            assert "LLMAuditLog" in r
            assert "weekly_summary" in r
