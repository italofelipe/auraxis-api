"""Governance of AI insight generation (#1546).

Covers the systemic fixes for unwanted/duplicated LLM generation:

- Scoped daily counters: chat usage must not consume the insights quota.
- Daily quota enforced inside the service (single point for REST + GraphQL).
- Premium entitlement enforced inside the service (GraphQL parity).
- Semantic dedupe by (user, insight_type, period_label) with ``force_regenerate``.
- Scheduled (cron) generations bypass and never consume the user quota.
- Stable context hash: market-price drift must not change the hash.
- ``GET /ai/insights/spending`` is read-only and never calls the LLM.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.services.llm_provider import StubLLMProvider

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_ai_chat.py)
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
    return str(login.get_json()["token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _current_user_id(app, token: str) -> uuid.UUID:
    with app.app_context():
        from flask_jwt_extended import decode_token

        return uuid.UUID(str(decode_token(token)["sub"]))


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


def _revoke_premium(app, user_id: uuid.UUID) -> None:
    with app.app_context():
        from app.services.entitlement_service import deactivate_premium

        deactivate_premium(user_id)


def _reset_ai_counter() -> None:
    from app.middleware.ai_rate_limit import _InMemoryAICounter

    _InMemoryAICounter.reset()


class _CountingStubProvider(StubLLMProvider):
    """Stub provider that counts generate_with_usage invocations."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_with_usage(
        self, prompt, *, response_schema=None, max_tokens=None, model=None
    ):
        self.calls += 1
        return super().generate_with_usage(
            prompt,
            response_schema=response_schema,
            max_tokens=max_tokens,
            model=model,
        )


class _ExplodingProvider(StubLLMProvider):
    """Provider that fails the test if the LLM is ever invoked."""

    def generate_with_usage(
        self, prompt, *, response_schema=None, max_tokens=None, model=None
    ):
        raise AssertionError("LLM must not be called on a read-only path")

    def generate(self, prompt):  # pragma: no cover — defensive
        raise AssertionError("LLM must not be called on a read-only path")


_ANCHOR = date(2026, 7, 10)


def _make_service(user_id: uuid.UUID, provider=None):
    from app.services.ai_advisory_service import AIAdvisoryService

    service = AIAdvisoryService(user_id=user_id)
    service._provider = provider or _CountingStubProvider()
    return service


# ---------------------------------------------------------------------------
# Scoped daily counters (middleware)
# ---------------------------------------------------------------------------


class TestScopedDailyCounters:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_chat_scope_is_isolated_from_insights_scope(self) -> None:
        from app.middleware.ai_rate_limit import (
            AI_CHAT_QUOTA_SCOPE,
            AI_INSIGHTS_QUOTA_SCOPE,
            get_ai_daily_usage,
            record_ai_daily_success,
        )

        user_id = uuid.uuid4()
        for _ in range(3):
            record_ai_daily_success(user_id, scope=AI_CHAT_QUOTA_SCOPE)

        chat_count, _ = get_ai_daily_usage(user_id, scope=AI_CHAT_QUOTA_SCOPE)
        insights_count, _ = get_ai_daily_usage(user_id, scope=AI_INSIGHTS_QUOTA_SCOPE)
        assert chat_count == 3
        assert insights_count == 0


# ---------------------------------------------------------------------------
# Service-level quota + entitlement (REST/GraphQL single enforcement point)
# ---------------------------------------------------------------------------


class TestServiceDailyQuota:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_generate_blocks_when_insights_quota_exhausted(self, app, client) -> None:
        token = _register_and_login(client, "quota-block")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            from app.middleware.ai_rate_limit import (
                AI_INSIGHTS_QUOTA_SCOPE,
                AIDailyLimitExceededError,
                record_ai_daily_success,
            )

            record_ai_daily_success(user_id, scope=AI_INSIGHTS_QUOTA_SCOPE)
            service = _make_service(user_id)
            with pytest.raises(AIDailyLimitExceededError):
                service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=_ANCHOR,
                )

    def test_scheduled_trigger_bypasses_quota_and_does_not_count(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "quota-cron")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            from app.middleware.ai_rate_limit import (
                AI_INSIGHTS_QUOTA_SCOPE,
                get_ai_daily_usage,
                record_ai_daily_success,
            )

            record_ai_daily_success(user_id, scope=AI_INSIGHTS_QUOTA_SCOPE)
            service = _make_service(user_id)
            result = service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
                trigger="scheduled",
            )
            assert result["cached"] is False
            count, _ = get_ai_daily_usage(user_id, scope=AI_INSIGHTS_QUOTA_SCOPE)
            assert count == 1  # unchanged — cron never consumes the user quota

    def test_user_generation_records_scoped_usage(self, app, client) -> None:
        token = _register_and_login(client, "quota-count")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            from app.middleware.ai_rate_limit import (
                AI_CHAT_QUOTA_SCOPE,
                AI_INSIGHTS_QUOTA_SCOPE,
                get_ai_daily_usage,
            )

            service = _make_service(user_id)
            result = service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
            )
            assert result["cached"] is False
            insights_count, _ = get_ai_daily_usage(
                user_id, scope=AI_INSIGHTS_QUOTA_SCOPE
            )
            chat_count, _ = get_ai_daily_usage(user_id, scope=AI_CHAT_QUOTA_SCOPE)
            assert insights_count == 1
            assert chat_count == 0

    def test_generate_requires_premium_entitlement(self, app, client) -> None:
        token = _register_and_login(client, "quota-free")
        user_id = _current_user_id(app, token)
        _revoke_premium(app, user_id)

        with app.app_context():
            from app.services.ai_advisory_service import AIEntitlementRequiredError

            service = _make_service(user_id)
            with pytest.raises(AIEntitlementRequiredError):
                service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=_ANCHOR,
                )

    def test_chat_requires_premium_entitlement(self, app, client) -> None:
        token = _register_and_login(client, "chat-free")
        user_id = _current_user_id(app, token)
        _revoke_premium(app, user_id)

        with app.app_context():
            from app.services.ai_advisory_service import AIEntitlementRequiredError

            service = _make_service(user_id)
            with pytest.raises(AIEntitlementRequiredError):
                service.answer_financial_question("Quanto gastei hoje?")

    def test_chat_blocks_when_chat_quota_exhausted(
        self, app, client, monkeypatch
    ) -> None:
        monkeypatch.setenv("AI_CHAT_DAILY_LIMIT", "2")
        token = _register_and_login(client, "chat-quota")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            from app.middleware.ai_rate_limit import (
                AI_CHAT_QUOTA_SCOPE,
                AIDailyLimitExceededError,
                record_ai_daily_success,
            )

            record_ai_daily_success(user_id, scope=AI_CHAT_QUOTA_SCOPE)
            record_ai_daily_success(user_id, scope=AI_CHAT_QUOTA_SCOPE)
            service = _make_service(user_id)
            with pytest.raises(AIDailyLimitExceededError):
                service.answer_financial_question("Quanto gastei hoje?")

    def test_chat_records_chat_scope_usage(self, app, client) -> None:
        token = _register_and_login(client, "chat-count")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            from app.middleware.ai_rate_limit import (
                AI_CHAT_QUOTA_SCOPE,
                AI_INSIGHTS_QUOTA_SCOPE,
                get_ai_daily_usage,
            )

            service = _make_service(user_id)
            result = service.answer_financial_question("Quanto gastei hoje?")
            assert result["answer"]
            chat_count, _ = get_ai_daily_usage(user_id, scope=AI_CHAT_QUOTA_SCOPE)
            insights_count, _ = get_ai_daily_usage(
                user_id, scope=AI_INSIGHTS_QUOTA_SCOPE
            )
            assert chat_count == 1
            assert insights_count == 0


# ---------------------------------------------------------------------------
# Semantic dedupe by (user, insight_type, period_label)
# ---------------------------------------------------------------------------


class TestSemanticDedupe:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_second_generation_same_period_returns_cached(self, app, client) -> None:
        token = _register_and_login(client, "dedupe")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            provider = _CountingStubProvider()
            service = _make_service(user_id, provider)
            first = service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
            )
            assert first["cached"] is False
            assert provider.calls == 1

            second = service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
            )
            assert second["cached"] is True
            assert second["id"] == first["id"]
            assert provider.calls == 1  # LLM not called again

    def test_dedupe_wins_over_quota_exhaustion(self, app, client) -> None:
        """A repeat request for an existing period returns cached, never 429."""
        token = _register_and_login(client, "dedupe-quota")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            service = _make_service(user_id)
            first = service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
            )
            assert first["cached"] is False
            # Quota is now exhausted (1/day) — but the repeat must serve cache.
            second = service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
            )
            assert second["cached"] is True

    def test_force_regenerate_bypasses_dedupe(self, app, client) -> None:
        token = _register_and_login(client, "dedupe-force")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            provider = _CountingStubProvider()
            service = _make_service(user_id, provider)
            first = service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
            )
            assert provider.calls == 1
            # scheduled trigger isolates the force flag from quota exhaustion
            second = service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
                force_regenerate=True,
                trigger="scheduled",
            )
            assert second["cached"] is False
            assert second["id"] != first["id"]
            assert provider.calls == 2

    def test_force_regenerate_still_respects_user_quota(self, app, client) -> None:
        token = _register_and_login(client, "force-quota")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            from app.middleware.ai_rate_limit import AIDailyLimitExceededError

            service = _make_service(user_id)
            service.generate_financial_insights(
                period_type="daily",
                anchor_date=_ANCHOR,
            )
            with pytest.raises(AIDailyLimitExceededError):
                service.generate_financial_insights(
                    period_type="daily",
                    anchor_date=_ANCHOR,
                    force_regenerate=True,
                )


# ---------------------------------------------------------------------------
# Stable context hash — volatile market data must not bust the cache
# ---------------------------------------------------------------------------


class TestStableContextHash:
    @staticmethod
    def _base_snapshot() -> dict:
        return {
            "schema_version": "financial_insight_snapshot.v2",
            "period": {"label": "2026-07-10"},
            "current_period": {"paid": {"balance": "100.00"}},
            "transactions": {
                "included_count": 1,
                "sample": [{"title": "Mercado", "amount": "100.00"}],
                "changes_since_last_generation": {"created_count": 2},
            },
            "wallet": {
                "items": [
                    {
                        "name": "PETR4",
                        "ticker": "PETR4",
                        "current_value": "50.00",
                        "invested_amount": "40.00",
                        "profit_loss_amount": "10.00",
                        "profit_loss_percent": "25.00",
                        "annual_rate": None,
                    }
                ],
                "total_value": "50.00",
                "total_current_value": "50.00",
                "total_invested_amount": "40.00",
                "total_profit_loss": "10.00",
                "total_profit_loss_percent": "25.00",
                "distribution": {"market_pct": "100.00"},
                "profile_alignment": {"alert_level": "aligned"},
                "benchmark": {"cdi_monthly_pct": "0.37"},
            },
            "projections": {"wallet": {"horizon_12m": "60.00"}},
        }

    def test_market_price_drift_keeps_hash_stable(self) -> None:
        from app.services.ai_advisory_service import (
            _financial_context_hash,
            _stable_context_projection,
        )

        first = self._base_snapshot()
        second = self._base_snapshot()
        second["wallet"]["items"][0]["current_value"] = "57.35"
        second["wallet"]["items"][0]["profit_loss_amount"] = "17.35"
        second["wallet"]["items"][0]["profit_loss_percent"] = "43.38"
        second["wallet"]["total_value"] = "57.35"
        second["wallet"]["total_current_value"] = "57.35"
        second["wallet"]["total_profit_loss"] = "17.35"
        second["wallet"]["total_profit_loss_percent"] = "43.38"
        second["wallet"]["benchmark"]["cdi_monthly_pct"] = "0.41"
        second["wallet"]["distribution"] = {"market_pct": "99.99"}
        second["wallet"]["profile_alignment"] = {"alert_level": "drift_warn"}
        second["projections"] = {"wallet": {"horizon_12m": "71.00"}}
        second["transactions"]["changes_since_last_generation"] = {"created_count": 5}

        assert _financial_context_hash(
            _stable_context_projection(first)
        ) == _financial_context_hash(_stable_context_projection(second))

    def test_transaction_change_still_changes_hash(self) -> None:
        from app.services.ai_advisory_service import (
            _financial_context_hash,
            _stable_context_projection,
        )

        first = self._base_snapshot()
        second = self._base_snapshot()
        second["transactions"]["sample"].append(
            {"title": "Farmácia", "amount": "35.00"}
        )
        second["transactions"]["included_count"] = 2

        assert _financial_context_hash(
            _stable_context_projection(first)
        ) != _financial_context_hash(_stable_context_projection(second))

    def test_wallet_holdings_identity_still_changes_hash(self) -> None:
        from app.services.ai_advisory_service import (
            _financial_context_hash,
            _stable_context_projection,
        )

        first = self._base_snapshot()
        second = self._base_snapshot()
        second["wallet"]["items"].append(
            {
                "name": "Tesouro Selic",
                "ticker": None,
                "current_value": "1000.00",
                "invested_amount": "1000.00",
                "profit_loss_amount": "0.00",
                "profit_loss_percent": "0.00",
                "annual_rate": "12.00",
            }
        )

        assert _financial_context_hash(
            _stable_context_projection(first)
        ) != _financial_context_hash(_stable_context_projection(second))


# ---------------------------------------------------------------------------
# Read-only spending insights (service + HTTP)
# ---------------------------------------------------------------------------


class TestReadSpendingInsights:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_returns_empty_and_never_calls_llm_when_no_insight(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "read-empty")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            service = _make_service(user_id, _ExplodingProvider())
            result = service.read_spending_insights()
            assert result["generated"] is False
            assert result["cached"] is False
            assert result["items"] == []
            assert result["tokens_used"] == 0

    def test_returns_persisted_insight_of_the_day(self, app, client) -> None:
        token = _register_and_login(client, "read-hit")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with app.app_context():
            from app.models.ai_insight import InsightType
            from app.services.ai_advisory_service import _save_insight

            today = date.today()
            _save_insight(
                user_id=user_id,
                content='[{"type":"resumo","title":"T","message":"M"}]',
                insight_type=InsightType.daily,
                period_label=today.strftime("%Y-%m-%d"),
                period_start=today,
                period_end=today,
                model="stub",
                tokens_used=10,
                cost_usd=Decimal("0.0001"),
                previous_insight_id=None,
            )
            service = _make_service(user_id, _ExplodingProvider())
            result = service.read_spending_insights()
            assert result["generated"] is True
            assert result["cached"] is True
            assert result["items"]

    def test_http_get_spending_is_read_only_and_deprecated(self, app, client) -> None:
        token = _register_and_login(client, "read-http")
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService."
            "generate_spending_insights"
        ) as generate_mock:
            for _ in range(3):
                resp = client.get("/ai/insights/spending", headers=_auth(token))
                assert resp.status_code == 200

        generate_mock.assert_not_called()
        assert resp.headers.get("Deprecation") == "true"
        payload = resp.get_json()
        data = payload.get("data") or payload
        assert data["generated"] is False


# ---------------------------------------------------------------------------
# HTTP governance on POST /ai/insights/generate and /ai/chat
# ---------------------------------------------------------------------------


class TestGenerateEndpointGovernance:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def _premium_user(self, app, client, prefix: str) -> tuple[str, uuid.UUID]:
        token = _register_and_login(client, prefix)
        user_id = _current_user_id(app, token)
        _grant_premium(app, user_id)
        return token, user_id

    def test_second_daily_generate_returns_cached_not_429(self, app, client) -> None:
        token, _ = self._premium_user(app, client, "http-dedupe")

        first = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        assert first.status_code == 200

        second = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        assert second.status_code == 200
        payload = second.get_json()
        data = payload.get("data") or payload
        assert data["cached"] is True

    def test_force_regenerate_when_quota_exhausted_returns_429(
        self, app, client
    ) -> None:
        token, _ = self._premium_user(app, client, "http-force")

        first = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        assert first.status_code == 200

        forced = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily", "force_regenerate": True},
            headers=_auth(token),
        )
        assert forced.status_code == 429
        assert forced.headers.get("Retry-After") is not None
        body = forced.get_json()
        assert "Limite diário" in str(body)

    def test_chat_does_not_consume_insights_quota(self, app, client) -> None:
        token, _ = self._premium_user(app, client, "http-scope")

        chat = client.post(
            "/ai/chat",
            json={"question": "Qual foi meu maior gasto?"},
            headers=_auth(token),
        )
        assert chat.status_code == 200

        generate = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        assert generate.status_code == 200
        payload = generate.get_json()
        data = payload.get("data") or payload
        assert data["cached"] is False
