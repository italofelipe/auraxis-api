"""Tests for the Ask-anything finance chat (#1521).

Covers:
- AIAdvisoryService.answer_financial_question (snapshot-grounded answer + audit)
- POST /ai/chat REST endpoint (entitlement gate, validation, happy path)
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from app.services.llm_provider import StubLLMProvider


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
