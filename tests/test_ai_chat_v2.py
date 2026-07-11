"""Chat assistente v2 (#1548): month-aware, period detection e function-calling.

Covers:
- detect_chat_period: pt-BR month names, "mês passado", "semana passada",
  "ontem", explicit YYYY-MM, default.
- build_chat_context: month window with labelled income samples — the
  "Salário BRQ de 01/07" case the daily-anchored snapshot could never answer.
- Tool loop: scripted provider issues tool_calls → tools execute read-only →
  final answer aggregates tokens; kill-switch and graceful fallback.
- execute_chat_tool: search/summary/pending are user-scoped and read-only.
- Chat payload carries period_label + tool_rounds (REST).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.extensions.database import db
from app.models.transaction import (
    Transaction,
    TransactionStatus,
    TransactionType,
)
from app.models.user import User
from app.services.chat_period_detection import detect_chat_period
from app.services.llm_provider import LLMResponse, StubLLMProvider

_TODAY = date(2026, 7, 10)


@pytest.fixture(autouse=True)
def _bypass_premium_gate():
    """Raw uuid users; the Premium gate (#1546) has dedicated coverage."""
    with patch("app.services.ai_advisory_service._ensure_premium_entitlement"):
        yield


def _make_user() -> uuid.UUID:
    user = User(
        name="Chat Cliente",
        email=f"chatv2-{uuid.uuid4().hex[:8]}@example.com",
        password="hashed",
    )
    db.session.add(user)
    db.session.commit()
    return user.id


def _make_tx(
    user_id: uuid.UUID,
    *,
    title: str,
    amount: str,
    tx_type: TransactionType = TransactionType.EXPENSE,
    status: TransactionStatus = TransactionStatus.PAID,
    due_date: date = _TODAY,
) -> Transaction:
    tx = Transaction(
        user_id=user_id,
        title=title,
        description=title,
        amount=Decimal(amount),
        type=tx_type,
        status=status,
        due_date=due_date,
    )
    db.session.add(tx)
    db.session.commit()
    return tx


class TestDetectChatPeriod:
    def test_month_name_resolves_to_nearest_non_future(self) -> None:
        result = detect_chat_period("quanto foi o salário de julho?", today=_TODAY)
        assert result.matched is True
        assert result.anchor == _TODAY  # July capped at today
        assert result.label == "julho/2026"

        december = detect_chat_period("gastos de dezembro", today=_TODAY)
        assert december.anchor == date(2025, 12, 31)
        assert december.label == "dezembro/2025"

    def test_month_name_with_explicit_year(self) -> None:
        result = detect_chat_period("resumo de maio de 2026", today=_TODAY)
        assert result.anchor == date(2026, 5, 31)
        assert result.label == "maio/2026"

    def test_explicit_yyyy_mm(self) -> None:
        result = detect_chat_period("resumo de 2026-06", today=_TODAY)
        assert result.anchor == date(2026, 6, 30)
        assert result.label == "junho/2026"

    def test_mes_passado(self) -> None:
        result = detect_chat_period("quanto gastei mês passado?", today=_TODAY)
        assert result.anchor == date(2026, 6, 30)
        assert result.label == "junho/2026"

    def test_semana_passada_and_ontem(self) -> None:
        week = detect_chat_period("e semana passada?", today=_TODAY)
        assert week.anchor == date(2026, 7, 3)
        yesterday = detect_chat_period("quanto gastei ontem?", today=_TODAY)
        assert yesterday.anchor == date(2026, 7, 9)

    def test_default_is_current_month_unmatched(self) -> None:
        result = detect_chat_period("qual meu maior gasto?", today=_TODAY)
        assert result.matched is False
        assert result.anchor == _TODAY
        assert result.label == "julho/2026"


class TestChatContextMonthAware:
    def test_salary_paid_on_day_one_is_visible_labelled(self, app) -> None:
        """The bug case: income from 01/07 must reach the model BY NAME."""
        with app.app_context():
            from app.services.financial_insight_context_builder import (
                FinancialInsightContextBuilder,
            )

            user_id = _make_user()
            _make_tx(
                user_id,
                title="Salário BRQ",
                amount="10754.00",
                tx_type=TransactionType.INCOME,
                due_date=date(2026, 7, 1),
            )
            context = FinancialInsightContextBuilder().build_chat_context(
                user_id=user_id,
                anchor_date=_TODAY,
                today=_TODAY,
            )

        titles = [item["title"] for item in context["transactions"]["sample"]]
        assert "Salário BRQ" in titles
        assert context["period"]["label"] == "2026-07"
        assert "pending_commitments" in context
        assert "month_summary" in context
        assert context["today"]["date"] == _TODAY.isoformat()

    def test_past_month_covers_whole_month(self, app) -> None:
        with app.app_context():
            from app.services.financial_insight_context_builder import (
                FinancialInsightContextBuilder,
            )

            user_id = _make_user()
            _make_tx(
                user_id,
                title="Bônus junho",
                amount="2000.00",
                tx_type=TransactionType.INCOME,
                due_date=date(2026, 6, 28),
            )
            context = FinancialInsightContextBuilder().build_chat_context(
                user_id=user_id,
                anchor_date=date(2026, 6, 30),
                today=_TODAY,
            )

        titles = [item["title"] for item in context["transactions"]["sample"]]
        assert "Bônus junho" in titles
        assert "today" not in context  # past month has no "today" highlight


class TestExecuteChatTool:
    def test_search_transactions_scoped_and_filtered(self, app) -> None:
        with app.app_context():
            from app.services.ai_chat_tools import execute_chat_tool

            user_id = _make_user()
            other_user = _make_user()
            _make_tx(
                user_id,
                title="Salário BRQ",
                amount="10754.00",
                tx_type=TransactionType.INCOME,
                due_date=date(2026, 7, 1),
            )
            _make_tx(
                other_user,
                title="Salário Alheio",
                amount="9999.00",
                tx_type=TransactionType.INCOME,
                due_date=date(2026, 7, 1),
            )

            result = execute_chat_tool(
                user_id=user_id,
                name="search_transactions",
                arguments={"query": "salário", "type": "income"},
            )

        titles = [item["title"] for item in result["items"]]
        assert titles == ["Salário BRQ"]

    def test_get_period_summary(self, app) -> None:
        with app.app_context():
            from app.services.ai_chat_tools import execute_chat_tool

            user_id = _make_user()
            _make_tx(
                user_id,
                title="Salário",
                amount="1000.00",
                tx_type=TransactionType.INCOME,
                due_date=date(2026, 7, 1),
            )
            _make_tx(user_id, title="Mercado", amount="400.00")

            result = execute_chat_tool(
                user_id=user_id,
                name="get_period_summary",
                arguments={"start_date": "2026-07-01", "end_date": "2026-07-31"},
            )

        assert result["paid"]["income_total"] == "1000.00"
        assert result["paid"]["expense_total"] == "400.00"
        assert result["paid"]["balance"] == "600.00"

    def test_unknown_tool_returns_error_payload(self, app) -> None:
        with app.app_context():
            from app.services.ai_chat_tools import execute_chat_tool

            result = execute_chat_tool(
                user_id=uuid.uuid4(), name="drop_tables", arguments={}
            )
        assert "error" in result


class _ScriptedToolProvider(StubLLMProvider):
    """Provider whose generate_chat first calls a tool, then answers."""

    def __init__(self) -> None:
        self.chat_calls = 0
        self.seen_tool_content: str | None = None

    def generate_chat(self, messages, *, tools=None, max_tokens=None, model=None):
        self.chat_calls += 1
        usage = LLMResponse(
            content="",
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            model=model or "gpt-4o-mini",
            latency_ms=5,
        )
        if self.chat_calls == 1:
            assert tools, "first round must offer tools"
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "search_transactions",
                            "arguments": json.dumps(
                                {"query": "salário", "type": "income"}
                            ),
                        },
                    }
                ],
            }
            return message, usage
        tool_messages = [m for m in messages if m.get("role") == "tool"]
        self.seen_tool_content = tool_messages[-1]["content"] if tool_messages else None
        final = {
            "role": "assistant",
            "content": "Seu salário de julho foi de R$ 10.754,00 (Salário BRQ).",
        }
        return final, usage


class TestToolLoop:
    def test_tool_loop_answers_salary_question(self, app, monkeypatch) -> None:
        monkeypatch.setenv("AI_CHAT_TOOLS_ENABLED", "1")
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = _make_user()
            _make_tx(
                user_id,
                title="Salário BRQ",
                amount="10754.00",
                tx_type=TransactionType.INCOME,
                due_date=date(2026, 7, 1),
            )
            provider = _ScriptedToolProvider()
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)

            result = service.answer_financial_question(
                "E o salário de julho, quanto foi?"
            )

        assert "10.754" in result["answer"]
        assert result["tool_rounds"] == 1
        assert result["period_label"] == "julho/2026"
        assert provider.chat_calls == 2
        # Tokens aggregated across the two rounds.
        assert result["tokens_used"] == 240
        # The tool result actually reached the model.
        assert provider.seen_tool_content is not None
        assert "Salário BRQ" in provider.seen_tool_content

    def test_kill_switch_falls_back_to_single_shot(self, app, monkeypatch) -> None:
        monkeypatch.setenv("AI_CHAT_TOOLS_ENABLED", "0")
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = _make_user()
            provider = _ScriptedToolProvider()
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)

            result = service.answer_financial_question("Quanto gastei hoje?")

        assert provider.chat_calls == 0  # tool loop never engaged
        assert result["tool_rounds"] == 0
        assert result["answer"]

    def test_tool_loop_failure_degrades_to_single_shot(self, app, monkeypatch) -> None:
        monkeypatch.setenv("AI_CHAT_TOOLS_ENABLED", "1")

        class _BrokenToolProvider(StubLLMProvider):
            def generate_chat(self, *args, **kwargs):
                raise RuntimeError("tool transport broke")

        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = _make_user()
            service = AIAdvisoryService(
                user_id=user_id, llm_provider=_BrokenToolProvider()
            )
            result = service.answer_financial_question("Quanto gastei hoje?")

        assert result["answer"]  # stub single-shot content
        assert result["tool_rounds"] == 0


class TestChatEndpointPayloadV2:
    def test_rest_payload_carries_period_label(self, app, client) -> None:
        token = _register_and_login(client, "chatv2-rest")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        resp = client.post(
            "/ai/chat",
            json={"question": "Quanto gastei em junho?"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data") or body
        assert data["period_label"] == "junho/2026"
        assert "tool_rounds" in data


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
    return str(login.get_json()["token"])


def _current_user_id(app, token: str) -> uuid.UUID:
    with app.app_context():
        from flask_jwt_extended import decode_token

        return uuid.UUID(str(decode_token(token)["sub"]))


def _grant_premium(app, user_id: uuid.UUID) -> None:
    with app.app_context():
        from app.models.entitlement import Entitlement, EntitlementSource

        db.session.add(
            Entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source=EntitlementSource.MANUAL,
                expires_at=None,
            )
        )
        db.session.commit()
