"""Tests for LGPD AI minimisation, consent gating and audit redaction (#1258).

Coverage areas:

- Consent gate blocks generation when AI consent is missing or revoked
- Prompt minimisation strips email, full name, UUIDs, JWT-like tokens and
  raw monetary amounts before the prompt reaches the LLM
- LLMAuditLog stores hashed/bounded markers instead of raw prompt/response
- AIInsight records carry a reference to the consent version that covered
  the generation (LGPD base legal — art. 7º, V/IX)
- Token counts and cost stay on LLMAuditLog (non-PII operational signals)
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.services.ai_lgpd import (
    AIConsentRequiredError,
    minimize_prompt_data,
    minimize_text,
    redact_prompt_for_audit,
    redact_response_for_audit,
)
from app.services.llm_provider import LLMResponse, StubLLMProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_user_and_consent(
    app, *, consent_state: str | None = "granted", version: str = "v1.0"
) -> uuid.UUID:
    """Create a real ``User`` row and optionally write a consent event.

    ``consent_state`` may be ``"granted"``, ``"revoked"`` or ``None``. The
    ``None`` case represents a user who has never interacted with the AI
    consent (so the gate must block).
    """
    from app.application.services.consent_service import record_consent
    from app.extensions.database import db
    from app.models.consent import ConsentAction, ConsentKind, ConsentSource
    from app.models.user import User

    with app.app_context():
        user = User(
            name="Italo Chagas",
            email=f"lgpd-ai-{uuid.uuid4().hex[:8]}@test.com",
            password="x",
        )
        db.session.add(user)
        db.session.commit()
        user_id: uuid.UUID = user.id  # type: ignore[assignment]

        if consent_state == "granted":
            record_consent(
                user_id=user_id,
                kind=ConsentKind.AI,
                version=version,
                action=ConsentAction.GRANTED,
                source=ConsentSource.API,
            )
        elif consent_state == "revoked":
            record_consent(
                user_id=user_id,
                kind=ConsentKind.AI,
                version=version,
                action=ConsentAction.GRANTED,
                source=ConsentSource.API,
            )
            record_consent(
                user_id=user_id,
                kind=ConsentKind.AI,
                version=version,
                action=ConsentAction.REVOKED,
                source=ConsentSource.API,
            )

        return user_id


def _capture_provider(
    content: str = '[{"type":"saude_financeira","title":"ok","message":"tudo bem."}]',
) -> MagicMock:
    """Return a provider mock that records the prompt it was called with."""
    provider = MagicMock()
    provider.generate_with_usage.return_value = LLMResponse(
        content=content,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        model="gpt-4o-mini",
        latency_ms=50,
    )
    return provider


# ---------------------------------------------------------------------------
# Minimisation helpers — pure unit tests
# ---------------------------------------------------------------------------


class TestMinimizeText:
    def test_email_is_redacted(self) -> None:
        out = minimize_text("contato: alice@example.com fim")
        assert "alice@example.com" not in out
        assert "[redacted]" in out

    def test_uuid_is_redacted(self) -> None:
        uid = "550e8400-e29b-41d4-a716-446655440000"
        out = minimize_text(f"id={uid}")
        assert uid not in out
        assert "[redacted]" in out

    def test_jwt_like_token_is_redacted(self) -> None:
        # gitleaks:allow — synthetic JWT fixture (header decodes to {"alg":"HS256"});
        # not a real secret. Exists purely to exercise the redaction regex.
        token = (  # pragma: allowlist secret
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdef"
        )
        out = minimize_text(f"Authorization: Bearer {token}")
        assert token not in out

    def test_brl_amount_is_redacted(self) -> None:
        out = minimize_text("Gastei R$ 1.234,56 com mercado")
        assert "1.234,56" not in out
        assert "[redacted]" in out

    def test_none_and_empty_return_empty(self) -> None:
        assert minimize_text(None) == ""
        assert minimize_text("") == ""


class TestMinimizePromptData:
    def test_email_and_name_keys_are_dropped(self) -> None:
        out = minimize_prompt_data({"email": "x@y.z", "name": "Italo", "ok": 1})
        assert "email" not in out
        assert "name" not in out
        assert out["ok"] == 1

    def test_uuid_keys_are_dropped(self) -> None:
        out = minimize_prompt_data({"user_id": "abc", "transaction_id": "1", "k": 2})
        assert "user_id" not in out
        assert "transaction_id" not in out
        assert out["k"] == 2

    def test_top_expenses_descriptions_are_collapsed(self) -> None:
        snapshot = {
            "total_income": 5000.0,
            "top_expenses": [
                {"description": "Pix para Maria Silva CPF 123", "total": 500.0},
                {"description": "Aluguel Rua das Flores 42", "total": 1500.0},
            ],
        }
        out = minimize_prompt_data(snapshot)
        descriptions = [row["description"] for row in out["top_expenses"]]
        for desc in descriptions:
            assert "Maria" not in desc
            assert "Pix" not in desc
            assert "Rua" not in desc

    def test_amounts_are_bucketed(self) -> None:
        out = minimize_prompt_data(
            {"total_income": 5000.0, "total_expense": 3000.0, "balance": 2000.0}
        )
        # Either a bucket label or a ~pct token — never the raw number.
        for key in ("total_expense", "balance"):
            assert out[key] != 3000.0
            assert out[key] != 2000.0
            assert "R$" in str(out[key]) or "%" in str(out[key]) or out[key] == "zero"


# ---------------------------------------------------------------------------
# Audit redaction helpers
# ---------------------------------------------------------------------------


class TestRedactPromptForAudit:
    def test_marker_contains_sha256_and_length(self) -> None:
        marker = redact_prompt_for_audit("hello world")
        assert marker.startswith("sha256:")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert expected in marker
        assert "len:11" in marker

    def test_consent_version_is_included_when_supplied(self) -> None:
        marker = redact_prompt_for_audit("p", consent_version="v2.3")
        assert "consent:v2.3" in marker

    def test_marker_does_not_contain_raw_prompt_text(self) -> None:
        prompt = "Resumo do mês para alice@example.com saldo R$ 1.234,56"
        marker = redact_prompt_for_audit(prompt)
        assert "alice@example.com" not in marker
        assert "1.234,56" not in marker


class TestRedactResponseForAudit:
    def test_preview_is_bounded_and_sanitised(self) -> None:
        long_response = "Olá alice@example.com seu saldo é R$ 1.000,00 " + ("x" * 1000)
        marker = redact_response_for_audit(long_response)
        assert "sha256:" in marker
        assert "alice@example.com" not in marker
        assert "1.000,00" not in marker
        # Preview is capped well below the full response length.
        preview = marker.split("preview:", 1)[1]
        assert len(preview) <= 240


# ---------------------------------------------------------------------------
# Consent gate — integration with AIAdvisoryService
# ---------------------------------------------------------------------------


@pytest.mark.no_ai_consent_patch
class TestConsentGate:
    """1. test_ai_blocked_when_consent_not_granted
    2. test_ai_blocked_when_consent_revoked
    3. test_ai_allowed_when_consent_granted
    4. test_consent_gate_blocks_goal_projection
    5. test_consent_gate_blocks_weekly_summary
    """

    def test_ai_blocked_when_consent_not_granted(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state=None)
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=StubLLMProvider())
            with pytest.raises(AIConsentRequiredError):
                service.generate_spending_insights()

    def test_ai_blocked_when_consent_revoked(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state="revoked")
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=StubLLMProvider())
            with pytest.raises(AIConsentRequiredError):
                service.generate_spending_insights()

    def test_ai_allowed_when_consent_granted(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state="granted")
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=StubLLMProvider())
            result = service.generate_spending_insights()
            assert "insights" in result
            assert result["model"] == "stub"

    def test_consent_gate_blocks_goal_projection(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state=None)
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=StubLLMProvider())
            with pytest.raises(AIConsentRequiredError):
                service.generate_goal_projection_narrative(
                    goal_id=uuid.uuid4(),
                    user_context="anything",
                    monthly_contribution=Decimal("100"),
                )

    def test_consent_gate_blocks_weekly_summary(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state="revoked")
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=StubLLMProvider())
            with pytest.raises(AIConsentRequiredError):
                service.generate_weekly_summary_narrative()


# ---------------------------------------------------------------------------
# Prompt sanitisation — observe what the LLM actually receives
# ---------------------------------------------------------------------------


class TestPromptSanitisation:
    """6. test_prompt_does_not_contain_user_email
    7. test_prompt_does_not_contain_raw_brl_amount
    8. test_prompt_for_goal_projection_strips_pii_from_user_context
    9. test_prompt_does_not_contain_uuid
    """

    def _generate(self, app, user_id: uuid.UUID, *, provider: MagicMock) -> str:
        """Run a generation and return the prompt the provider received."""
        with app.app_context():
            from app.extensions.database import db
            from app.models.transaction import (
                Transaction,
                TransactionStatus,
                TransactionType,
            )
            from app.services.ai_advisory_service import AIAdvisoryService

            # Seed a transaction with a description that carries PII so we
            # can verify the minimiser strips it before the prompt is sent.
            tx = Transaction(
                user_id=user_id,
                title="pii-tx",
                description=(
                    "Pix para alice@example.com 550e8400-e29b-41d4-a716-446655440000"
                ),
                amount=Decimal("1234.56"),
                type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=__import__("datetime").date.today(),
                deleted=False,
            )
            db.session.add(tx)
            db.session.commit()

            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            service.generate_spending_insights()

        # Capture the prompt the LLM provider was called with.
        call = provider.generate_with_usage.call_args
        assert call is not None
        prompt = call.args[0] if call.args else call.kwargs.get("prompt", "")
        return str(prompt)

    def test_prompt_does_not_contain_user_email(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state="granted")
        prompt = self._generate(app, user_id, provider=_capture_provider())
        assert "alice@example.com" not in prompt

    def test_prompt_does_not_contain_uuid(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state="granted")
        prompt = self._generate(app, user_id, provider=_capture_provider())
        assert "550e8400-e29b-41d4-a716-446655440000" not in prompt

    def test_prompt_does_not_contain_raw_brl_amount(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state="granted")
        prompt = self._generate(app, user_id, provider=_capture_provider())
        # The original transaction was R$ 1234.56 — no raw value should appear.
        assert "1234.56" not in prompt
        assert "1.234,56" not in prompt

    def test_prompt_for_goal_projection_strips_pii_from_user_context(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state="granted")
        with app.app_context():
            from app.extensions.database import db
            from app.models.goal import Goal
            from app.services.ai_advisory_service import AIAdvisoryService

            goal = Goal(
                user_id=user_id,
                title="Viagem 550e8400-e29b-41d4-a716-446655440000",
                target_amount=Decimal("10000"),
                current_amount=Decimal("1000"),
                status="active",
            )
            db.session.add(goal)
            db.session.commit()

            provider = _capture_provider("Sua meta vai bem.")
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            service.generate_goal_projection_narrative(
                goal_id=goal.id,
                user_context=(
                    "Quero juntar R$ 5.000,00 e me chamo Italo, email italo@example.com"
                ),
                monthly_contribution=Decimal("200"),
            )

            call = provider.generate_with_usage.call_args
            prompt = call.args[0] if call.args else call.kwargs.get("prompt", "")

            assert "italo@example.com" not in prompt
            assert "5.000,00" not in prompt
            assert "550e8400-e29b-41d4-a716-446655440000" not in prompt


# ---------------------------------------------------------------------------
# LLMAuditLog redaction
# ---------------------------------------------------------------------------


class TestLLMAuditLogRedaction:
    """10. test_llm_audit_log_does_not_store_raw_prompt_text
    11. test_llm_audit_log_keeps_token_counts_and_cost
    12. test_llm_audit_log_response_text_is_bounded_preview
    """

    def _run(self, app, *, provider_content: str = "Mensagem do modelo") -> None:
        user_id = _create_user_and_consent(app, consent_state="granted")
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            provider = MagicMock()
            provider.generate_with_usage.return_value = LLMResponse(
                content=(
                    '[{"type":"saude_financeira","title":"ok",'
                    '"message":"' + provider_content + '"}]'
                ),
                prompt_tokens=100,
                completion_tokens=200,
                total_tokens=300,
                model="gpt-4o-mini",
                latency_ms=150,
            )
            service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
            service.generate_spending_insights()
            return user_id

    def test_llm_audit_log_does_not_store_raw_prompt_text(self, app) -> None:
        user_id = self._run(app)
        with app.app_context():
            from app.models.llm_audit_log import LLMAuditLog

            row = LLMAuditLog.query.filter_by(user_id=user_id).first()
            assert row is not None
            # The redacted marker is short and starts with "sha256:".
            assert row.prompt.startswith("sha256:")
            # The full LLM prompt template contains the marker phrase
            # "Você é um consultor financeiro pessoal" — it must NOT survive.
            assert "consultor financeiro pessoal" not in row.prompt

    def test_llm_audit_log_keeps_token_counts_and_cost(self, app) -> None:
        user_id = self._run(app)
        with app.app_context():
            from app.models.llm_audit_log import LLMAuditLog

            row = LLMAuditLog.query.filter_by(user_id=user_id).first()
            assert row is not None
            assert row.prompt_tokens == 100
            assert row.completion_tokens == 200
            assert row.total_tokens == 300
            assert float(row.estimated_cost_usd) > 0
            assert row.latency_ms == 150
            assert row.model == "gpt-4o-mini"
            assert row.endpoint == "spending_insights"

    def test_llm_audit_log_response_text_is_bounded_preview(self, app) -> None:
        user_id = self._run(app, provider_content="x" * 5000)
        with app.app_context():
            from app.models.llm_audit_log import LLMAuditLog

            row = LLMAuditLog.query.filter_by(user_id=user_id).first()
            assert row is not None
            assert row.response_text.startswith("sha256:")
            # Length tag is present and the stored value is bounded.
            assert "len:" in row.response_text
            assert len(row.response_text) < 1000


# ---------------------------------------------------------------------------
# AIInsight consent-version traceability
# ---------------------------------------------------------------------------


@pytest.mark.no_ai_consent_patch
class TestAIInsightConsentTraceability:
    """13. test_ai_insight_records_consent_version
    14. test_audit_log_marker_includes_consent_version
    """

    def test_ai_insight_records_consent_version(self, app) -> None:
        """The consent version that covered a generation must be reachable
        from the resulting insight.

        ``AIInsight`` itself does not yet carry a dedicated column for the
        consent version — a follow-up migration is planned — so the link is
        currently expressed via the audit row written in the same
        transaction: there is exactly one ``LLMAuditLog`` row per generated
        ``AIInsight``, and that row carries the version marker.
        """
        user_id = _create_user_and_consent(app, consent_state="granted", version="v2.5")
        with app.app_context():
            from app.models.ai_insight import AIInsight
            from app.models.llm_audit_log import LLMAuditLog
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=StubLLMProvider())
            service.generate_spending_insights()

            insight = AIInsight.query.filter_by(user_id=user_id).first()
            audit = LLMAuditLog.query.filter_by(user_id=user_id).first()
            assert insight is not None
            assert audit is not None
            assert "consent:v2.5" in audit.prompt

    def test_audit_log_marker_includes_consent_version(self, app) -> None:
        user_id = _create_user_and_consent(app, consent_state="granted", version="v9.9")
        with app.app_context():
            from app.models.llm_audit_log import LLMAuditLog
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=user_id, llm_provider=StubLLMProvider())
            service.generate_spending_insights()

            row = LLMAuditLog.query.filter_by(user_id=user_id).first()
            assert row is not None
            assert "consent:v9.9" in row.prompt


# ---------------------------------------------------------------------------
# REST controller mapping — AIConsentRequiredError → 403
# ---------------------------------------------------------------------------


@pytest.mark.no_ai_consent_patch
class TestAIControllerConsentMapping:
    def _register_and_login_and_premium(self, app, client, prefix: str) -> str:
        import uuid as _uuid

        suffix = _uuid.uuid4().hex[:8]
        email = f"{prefix}-{suffix}@test.com"
        password = "StrongPass@123"
        reg = client.post(
            "/auth/register",
            json={"name": f"{prefix}-{suffix}", "email": email, "password": password},
        )
        assert reg.status_code == 201
        login = client.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        token = login.get_json()["token"]

        from flask_jwt_extended import decode_token

        with app.app_context():
            user_id = _uuid.UUID(decode_token(token)["sub"])
            from app.extensions.database import db
            from app.models.entitlement import Entitlement, EntitlementSource

            ent = Entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source=EntitlementSource.MANUAL,
                expires_at=None,
            )
            db.session.add(ent)
            db.session.commit()

        return token

    def test_generate_returns_403_without_ai_consent(self, app, client) -> None:
        # LGPD gate lives on the GENERATION path (LLM processing). The old
        # GET /ai/insights/spending became read-only in #1546 — reading one's
        # own persisted insight is not LLM processing and needs no consent.
        token = self._register_and_login_and_premium(app, client, "ai-no-consent")
        # Request the standard contract envelope so we can assert on
        # ``error_code`` (legacy envelope only carries a free-text message).
        resp = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers={
                "Authorization": f"Bearer {token}",
                "X-API-Contract": "v2",
            },
        )
        assert resp.status_code == 403
        body = resp.get_json() or {}
        # Error code must identify the LGPD path so the frontend can route
        # the user to the consent flow.
        assert "AI_CONSENT_REQUIRED" in str(body)

    def test_spending_read_is_consent_free(self, app, client) -> None:
        """Read-only path (#1546): no LLM processing → no consent required."""
        token = self._register_and_login_and_premium(app, client, "ai-read-free")
        resp = client.get(
            "/ai/insights/spending",
            headers={
                "Authorization": f"Bearer {token}",
                "X-API-Contract": "v2",
            },
        )
        assert resp.status_code == 200


__all__ = []
