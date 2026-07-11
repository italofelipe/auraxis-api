"""Tests for the Ask-anything finance chat (#1521).

Covers:
- AIAdvisoryService.answer_financial_question (snapshot-grounded answer + audit)
- POST /ai/chat REST endpoint (entitlement gate, validation, happy path)
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import patch

from app.services.llm_provider import LLMProviderError, StubLLMProvider

_SERVICE_TARGET = (
    "app.services.ai_advisory_service.AIAdvisoryService.answer_financial_question"
)


def _gql(client, query: str, token: str, variables: dict | None = None):
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers={
            "Content-Type": "application/json",
            "X-API-Contract": "v2",
            "Authorization": f"Bearer {token}",
        },
    )


_ASK_MUTATION = """
mutation Ask($question: String!) {
  askFinancialQuestion(question: $question) {
    ok
    answer
    model
    tokensUsed
    costUsd
  }
}
"""


def _register_and_login(client, prefix: str) -> str:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@test.com"
    password = "StrongPass@123"
    client.post(
        "/auth/register",
        json={"name": prefix, "email": email, "password": password},
    )
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.get_json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _current_user_id(app, token: str) -> uuid.UUID:
    with app.app_context():
        from flask_jwt_extended import decode_token

        return uuid.UUID(decode_token(token)["sub"])


def _grant_premium(app, user_id: uuid.UUID) -> None:
    with app.app_context():
        from app.extensions.database import db
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


class TestAnswerFinancialQuestionService:
    def test_returns_answer_and_writes_audit(self, app) -> None:
        with app.app_context():
            from app.models.llm_audit_log import LLMAuditLog
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            service = AIAdvisoryService(user_id=user_id, llm_provider=StubLLMProvider())

            # Entitlement gate now lives inside the service (#1546); this unit
            # test uses a raw uuid without user row, so bypass the gate.
            with patch("app.services.ai_advisory_service._ensure_premium_entitlement"):
                result = service.answer_financial_question("Quanto gastei hoje?")

            assert result["answer"]
            assert result["model"] == "stub"
            assert result["tokens_used"] > 0
            log_row = LLMAuditLog.query.filter_by(
                user_id=user_id, endpoint="chat_ask_anything"
            ).first()
            assert log_row is not None

    def test_empty_question_raises_value_error(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(
                user_id=uuid.uuid4(), llm_provider=StubLLMProvider()
            )
            try:
                service.answer_financial_question("   ")
            except ValueError:
                return
            raise AssertionError("expected ValueError for empty question")


class TestAIChatEndpoint:
    def test_requires_premium(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-chat-free")
        user_id = _current_user_id(app, token)
        # New users get a trial entitlement; revoke it to exercise the gate.
        with app.app_context():
            from app.services.entitlement_service import deactivate_premium

            deactivate_premium(user_id)
        resp = client.post(
            "/ai/chat", json={"question": "Quanto gastei?"}, headers=_auth(token)
        )
        assert resp.status_code == 403

    def test_rejects_missing_question(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-chat-bad")
        _grant_premium(app, _current_user_id(app, token))
        resp = client.post("/ai/chat", json={}, headers=_auth(token))
        assert resp.status_code == 400

    def test_happy_path_returns_answer(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-chat-ok")
        _grant_premium(app, _current_user_id(app, token))

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.answer_financial_question",
            return_value={
                "answer": "Você gastou R$120,00 hoje.",
                "model": "stub",
                "tokens_used": 42,
                "cost_usd": 0.0,
            },
        ) as mocked:
            resp = client.post(
                "/ai/chat",
                json={"question": "Quanto gastei hoje?"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data") or body
        assert "Você gastou" in data["answer"]
        mocked.assert_called_once()

    def test_budget_exceeded_returns_429(self, app, client) -> None:
        from app.services.ai_advisory_service import AIInsightCostBudgetExceededError

        token = _register_and_login(client, prefix="ai-chat-budget")
        _grant_premium(app, _current_user_id(app, token))
        with patch(
            _SERVICE_TARGET,
            side_effect=AIInsightCostBudgetExceededError(
                "Orçamento mensal atingido.",
                scope="user_monthly",
                limit_usd=Decimal("2.72"),
                spent_usd=Decimal("3.00"),
            ),
        ):
            resp = client.post(
                "/ai/chat", json={"question": "E aí?"}, headers=_auth(token)
            )
        assert resp.status_code == 429

    def test_consent_required_returns_403(self, app, client) -> None:
        from app.services.ai_lgpd import AIConsentRequiredError

        token = _register_and_login(client, prefix="ai-chat-consent")
        _grant_premium(app, _current_user_id(app, token))
        with patch(_SERVICE_TARGET, side_effect=AIConsentRequiredError()):
            resp = client.post(
                "/ai/chat", json={"question": "E aí?"}, headers=_auth(token)
            )
        assert resp.status_code == 403

    def test_llm_error_returns_500(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-chat-llm")
        _grant_premium(app, _current_user_id(app, token))
        with patch(_SERVICE_TARGET, side_effect=LLMProviderError("boom")):
            resp = client.post(
                "/ai/chat", json={"question": "E aí?"}, headers=_auth(token)
            )
        assert resp.status_code == 500

    def test_unexpected_error_returns_500(self, app, client) -> None:
        token = _register_and_login(client, prefix="ai-chat-boom")
        _grant_premium(app, _current_user_id(app, token))
        with patch(_SERVICE_TARGET, side_effect=RuntimeError("unexpected")):
            resp = client.post(
                "/ai/chat", json={"question": "E aí?"}, headers=_auth(token)
            )
        assert resp.status_code == 500


class TestAskFinancialQuestionGraphQL:
    def test_happy_path(self, app, client) -> None:
        token = _register_and_login(client, prefix="gql-chat-ok")
        _grant_premium(app, _current_user_id(app, token))
        with patch(
            _SERVICE_TARGET,
            return_value={
                "answer": "Saldo positivo.",
                "model": "stub",
                "tokens_used": 10,
                "cost_usd": 0.0,
            },
        ):
            resp = _gql(client, _ASK_MUTATION, token, {"question": "Como estou?"})
        body = resp.get_json()
        assert not body.get("errors")
        payload = body["data"]["askFinancialQuestion"]
        assert payload["ok"] is True
        assert payload["answer"] == "Saldo positivo."

    def test_rejects_empty_question(self, app, client) -> None:
        token = _register_and_login(client, prefix="gql-chat-empty")
        resp = _gql(client, _ASK_MUTATION, token, {"question": "   "})
        body = resp.get_json()
        assert body.get("errors")

    def test_maps_llm_provider_error(self, app, client) -> None:
        token = _register_and_login(client, prefix="gql-chat-llm")
        _grant_premium(app, _current_user_id(app, token))
        with patch(_SERVICE_TARGET, side_effect=LLMProviderError("boom")):
            resp = _gql(client, _ASK_MUTATION, token, {"question": "Como estou?"})
        body = resp.get_json()
        assert body.get("errors")


class TestAnswerFinancialQuestionProviderError:
    def test_propagates_llm_provider_error(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            class _RaisingProvider:
                def generate_with_usage(self, prompt, **_kwargs):
                    raise LLMProviderError("boom")

            service = AIAdvisoryService(
                user_id=uuid.uuid4(), llm_provider=_RaisingProvider()
            )
            try:
                with patch(
                    "app.services.ai_advisory_service._ensure_premium_entitlement"
                ):
                    service.answer_financial_question("Quanto tenho?")
            except LLMProviderError:
                return
            raise AssertionError("expected LLMProviderError to propagate")
