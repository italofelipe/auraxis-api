"""Cost ceiling + monthly cap enforcement for AI insights (#1386, slice A).

Covers:
- Per-user monthly LLM budget = 50% of the Premium plan price (FX-adjusted).
- Per-user month-to-date cost enforcement (isolated per user).
- Monthly generation counter (30/month) + HTTP 429 at the cap.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest


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


def _auth(token: str, v2: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if v2:
        headers["X-API-Contract"] = "v2"
    return headers


def _grant_premium(app, token: str) -> uuid.UUID:
    with app.app_context():
        from flask_jwt_extended import decode_token

        from app.extensions.database import db
        from app.models.entitlement import Entitlement, EntitlementSource

        user_id = uuid.UUID(decode_token(token)["sub"])
        db.session.add(
            Entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source=EntitlementSource.MANUAL,
                expires_at=None,
            )
        )
        db.session.commit()
        return user_id


def _reset_ai_counter() -> None:
    from app.middleware.ai_rate_limit import _InMemoryAICounter

    _InMemoryAICounter.reset()


def _seed_llm_cost(
    user_id: uuid.UUID,
    *,
    cost_usd: str,
    endpoint: str,
    created_at: datetime | None = None,
) -> None:
    from app.extensions.database import db
    from app.models.llm_audit_log import LLMAuditLog

    # Stamp created_at explicitly when the test enforces a specific month window —
    # sem isso a linha cai no mês corrente real e o enforcement (que consulta a
    # janela do `now` do teste) não a enxerga, quebrando o teste fora de maio/2026.
    entry = LLMAuditLog(
        user_id=user_id,
        endpoint=endpoint,
        model="gpt-4o-mini",
        prompt="p",
        response_text="r",
        prompt_tokens=10,
        completion_tokens=10,
        total_tokens=20,
        estimated_cost_usd=Decimal(cost_usd),
        latency_ms=10,
    )
    if created_at is not None:
        entry.created_at = created_at
    db.session.add(entry)
    db.session.commit()


# ---------------------------------------------------------------------------
# Per-user budget computation
# ---------------------------------------------------------------------------


class TestUserBudgetComputation:
    def test_default_budget_is_half_plan_price_in_usd(self) -> None:
        from app.services.ai_advisory_service import _user_ai_insight_monthly_budget_usd

        # R$29,90 * 0.5 / 5.50 ≈ 2.7182 USD
        budget = _user_ai_insight_monthly_budget_usd()
        assert abs(budget - Decimal("2.718181818")) < Decimal("0.001")

    def test_env_overrides_pct_and_fx(self) -> None:
        from app.services.ai_advisory_service import _user_ai_insight_monthly_budget_usd

        with patch.dict(
            "os.environ",
            {"AI_INSIGHTS_USER_BUDGET_PCT": "0.25", "AI_INSIGHTS_BRL_USD_FX": "5.00"},
        ):
            # 29.90 * 0.25 / 5.00 = 1.495
            assert _user_ai_insight_monthly_budget_usd() == Decimal("1.495")


# ---------------------------------------------------------------------------
# Per-user cost enforcement
# ---------------------------------------------------------------------------


class TestUserCostEnforcement:
    def test_raises_when_user_month_spend_reaches_budget(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import (
                AIInsightCostBudgetExceededError,
                _enforce_ai_insight_user_cost_budget,
            )

            user_id = uuid.uuid4()
            now = datetime(2026, 5, 15, 12, 0, 0)
            # Budget ≈ 2.72 USD; seed 3.00 this month.
            _seed_llm_cost(
                user_id,
                cost_usd="3.00",
                endpoint="financial_insights_daily",
                created_at=now,
            )
            with pytest.raises(AIInsightCostBudgetExceededError) as exc:
                _enforce_ai_insight_user_cost_budget(user_id=user_id, now=now)
            assert exc.value.scope == "user_monthly"

    def test_does_not_raise_below_budget(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import (
                _enforce_ai_insight_user_cost_budget,
            )

            user_id = uuid.uuid4()
            now = datetime(2026, 5, 15, 12, 0, 0)
            _seed_llm_cost(
                user_id,
                cost_usd="0.50",
                endpoint="financial_insights_daily",
                created_at=now,
            )
            # Must not raise.
            _enforce_ai_insight_user_cost_budget(user_id=user_id, now=now)

    def test_monthly_recap_is_exempt_from_cost_ceiling(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import (
                _enforce_financial_insight_generation_budget,
            )

            user_id = uuid.uuid4()
            _seed_llm_cost(
                user_id, cost_usd="100.00", endpoint="financial_insights_daily"
            )
            # Monthly recap is a guaranteed deliverable → never blocked by budget.
            _enforce_financial_insight_generation_budget(
                user_id=user_id,
                normalized_period_type="monthly",
                preview_run=None,
            )

    def test_spend_is_isolated_per_user(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import (
                _enforce_ai_insight_user_cost_budget,
            )

            spender = uuid.uuid4()
            other = uuid.uuid4()
            now = datetime(2026, 5, 15, 12, 0, 0)
            _seed_llm_cost(
                spender, cost_usd="5.00", endpoint="financial_insights_daily"
            )
            # The other user has no spend → not blocked by spender's cost.
            _enforce_ai_insight_user_cost_budget(user_id=other, now=now)


# ---------------------------------------------------------------------------
# Monthly generation cap (30/month)
# ---------------------------------------------------------------------------


class TestMonthlyCounter:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_record_and_get_monthly_usage(self) -> None:
        from app.middleware.ai_rate_limit import (
            get_ai_monthly_usage,
            record_ai_monthly_success,
        )

        user_id = uuid.uuid4()
        for _ in range(3):
            record_ai_monthly_success(user_id)
        count, ttl = get_ai_monthly_usage(user_id)
        assert count == 3
        assert ttl > 0

    def test_monthly_usage_isolated_per_user(self) -> None:
        from app.middleware.ai_rate_limit import (
            get_ai_monthly_usage,
            record_ai_monthly_success,
        )

        a, b = uuid.uuid4(), uuid.uuid4()
        record_ai_monthly_success(a)
        count_b, _ = get_ai_monthly_usage(b)
        assert count_b == 0


class TestMonthlyCapHTTP:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_returns_429_when_monthly_cap_reached(self, app, client) -> None:
        from app.middleware.ai_rate_limit import (
            AI_MONTHLY_LIMIT,
            record_ai_monthly_success,
        )

        token = _register_and_login(client, "ai-monthly-cap")
        user_id = _grant_premium(app, token)

        # Saturate the monthly counter (daily stays at 0, so the monthly cap is
        # the gate that trips).
        for _ in range(AI_MONTHLY_LIMIT):
            record_ai_monthly_success(user_id)

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_spending_insights",
            return_value={
                "insights": "ok",
                "tokens_used": 10,
                "cost_usd": 0.0,
                "month": "2026-05",
                "model": "stub",
            },
        ):
            resp = client.get("/ai/insights/spending", headers=_auth(token, v2=True))

        assert resp.status_code == 429
        assert resp.get_json()["error"]["code"] == "AI_MONTHLY_LIMIT_EXCEEDED"
        assert resp.headers.get("X-AI-Calls-Remaining-Month") == "0"


# ---------------------------------------------------------------------------
# Admin bypass — admins are exempt from caps and cost ceiling (for testing)
# ---------------------------------------------------------------------------


class TestAdminBypass:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_request_is_admin_reads_roles_claim(self) -> None:
        from app.middleware.ai_rate_limit import request_is_admin

        admin_ctx = type("Ctx", (), {"roles": ["admin"]})()
        user_ctx = type("Ctx", (), {"roles": ["user"]})()
        with patch("app.auth.get_active_auth_context", return_value=admin_ctx):
            assert request_is_admin() is True
        with patch("app.auth.get_active_auth_context", return_value=user_ctx):
            assert request_is_admin() is False

    def test_admin_bypasses_daily_and_monthly_caps(self, app, client) -> None:
        from app.middleware.ai_rate_limit import AI_MONTHLY_LIMIT

        token = _register_and_login(client, "ai-admin")
        user_id = _grant_premium(app, token)
        # Pre-saturate both counters; an admin must still pass through.
        from app.middleware.ai_rate_limit import record_ai_monthly_success

        for _ in range(AI_MONTHLY_LIMIT):
            record_ai_monthly_success(user_id)

        with (
            patch(
                "app.middleware.ai_rate_limit.request_is_admin",
                return_value=True,
            ),
            patch(
                "app.services.ai_advisory_service.AIAdvisoryService.generate_spending_insights",
                return_value={
                    "insights": "ok",
                    "tokens_used": 10,
                    "cost_usd": 0.0,
                    "month": "2026-05",
                    "model": "stub",
                },
            ),
        ):
            first = client.get("/ai/insights/spending", headers=_auth(token, v2=True))
            second = client.get("/ai/insights/spending", headers=_auth(token, v2=True))

        assert first.status_code == 200
        assert second.status_code == 200  # would be 429 for a non-admin

    def test_admin_bypasses_cost_ceiling(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import (
                _enforce_financial_insight_generation_budget,
            )

            user_id = uuid.uuid4()
            _seed_llm_cost(
                user_id, cost_usd="100.00", endpoint="financial_insights_daily"
            )
            with patch(
                "app.middleware.ai_rate_limit.request_is_admin",
                return_value=True,
            ):
                # Far above budget, but an admin must not be blocked.
                _enforce_financial_insight_generation_budget(
                    user_id=user_id,
                    normalized_period_type="daily",
                    preview_run=None,
                )
