"""Tests for AI daily rate limit middleware (#1214, reworked in #1546).

Coverage areas:
- _seconds_until_midnight_brt() returns positive int <= 86400
- _brt_date_str() returns YYYY-MM-DD format
- check_ai_daily_limit(): 1st call → count 1, 2nd → count 2, 3rd → count 3
- InMemoryAICounter.reset() clears state
- HTTP POST /ai/insights/generate (quota now enforced inside the service):
    - 1st call → 200 + X-AI-Calls-Remaining: 0 (1/day consumed)
    - repeat same period → 200 cached (semantic dedupe wins over quota)
    - force_regenerate with quota exhausted → 429 AI_DAILY_LIMIT_EXCEEDED
    - provider failures and cached responses do not consume the daily allowance
- HTTP GET /ai/insights/spending is read-only (#1546): never generates,
  never consumes quota, always 200 for Premium.
- Free user still gets 403 from entitlement gate (never reaches rate limit)
- Goal projection endpoint NOT rate-limited (not /ai/insights/*)
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.services.llm_provider import LLMProviderError

# ---------------------------------------------------------------------------
# Helpers (same pattern as test_ai_advisory_service.py)
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


def _auth(token: str, v2: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if v2:
        headers["X-API-Contract"] = "v2"
    return headers


def _revoke_premium(app, token: str) -> None:
    with app.app_context():
        from flask_jwt_extended import decode_token

        from app.services.entitlement_service import deactivate_premium

        user_id = uuid.UUID(decode_token(token)["sub"])
        deactivate_premium(user_id)


def _grant_premium(app, token: str) -> None:
    with app.app_context():
        from flask_jwt_extended import decode_token

        from app.extensions.database import db
        from app.models.entitlement import Entitlement, EntitlementSource

        user_id = uuid.UUID(decode_token(token)["sub"])
        for key in ("advanced_simulations",):
            ent = Entitlement(
                user_id=user_id,
                feature_key=key,
                source=EntitlementSource.MANUAL,
                expires_at=None,
            )
            db.session.add(ent)
        db.session.commit()


def _reset_ai_counter() -> None:
    from app.middleware.ai_rate_limit import _InMemoryAICounter

    _InMemoryAICounter.reset()


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


class TestMidnightHelpers:
    def test_seconds_until_midnight_positive(self) -> None:
        from app.middleware.ai_rate_limit import _seconds_until_midnight_brt

        secs = _seconds_until_midnight_brt()
        assert 0 < secs <= 86_400

    def test_brt_date_str_format(self) -> None:
        from app.middleware.ai_rate_limit import _brt_date_str

        s = _brt_date_str()
        assert len(s) == 10
        parts = s.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day


# ---------------------------------------------------------------------------
# Unit tests — InMemoryAICounter
# ---------------------------------------------------------------------------


class TestInMemoryAICounter:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_increments_sequentially(self) -> None:
        from app.middleware.ai_rate_limit import _InMemoryAICounter

        key = f"test-key-{uuid.uuid4().hex}"
        assert _InMemoryAICounter.incr(key, 100) == 1
        assert _InMemoryAICounter.incr(key, 100) == 2
        assert _InMemoryAICounter.incr(key, 100) == 3

    def test_reset_clears_all(self) -> None:
        from app.middleware.ai_rate_limit import _InMemoryAICounter

        key = f"test-key-{uuid.uuid4().hex}"
        _InMemoryAICounter.incr(key, 100)
        _InMemoryAICounter.reset()
        assert _InMemoryAICounter.incr(key, 100) == 1

    def test_different_keys_are_independent(self) -> None:
        from app.middleware.ai_rate_limit import _InMemoryAICounter

        key_a = f"key-a-{uuid.uuid4().hex}"
        key_b = f"key-b-{uuid.uuid4().hex}"
        _InMemoryAICounter.incr(key_a, 100)
        _InMemoryAICounter.incr(key_a, 100)
        assert _InMemoryAICounter.incr(key_b, 100) == 1


# ---------------------------------------------------------------------------
# Unit tests — check_ai_daily_limit
# ---------------------------------------------------------------------------


class TestCheckAiDailyLimit:
    def setup_method(self) -> None:
        _reset_ai_counter()

    def test_first_call_returns_count_one(self) -> None:
        from app.middleware.ai_rate_limit import check_ai_daily_limit

        user_id = uuid.uuid4()
        count, retry_after = check_ai_daily_limit(user_id, max_calls=2)
        assert count == 1
        assert retry_after > 0

    def test_second_call_returns_count_two(self) -> None:
        from app.middleware.ai_rate_limit import check_ai_daily_limit

        user_id = uuid.uuid4()
        check_ai_daily_limit(user_id, max_calls=2)
        count, _ = check_ai_daily_limit(user_id, max_calls=2)
        assert count == 2

    def test_third_call_returns_count_three_exceeds_limit(self) -> None:
        from app.middleware.ai_rate_limit import check_ai_daily_limit

        user_id = uuid.uuid4()
        check_ai_daily_limit(user_id, max_calls=2)
        check_ai_daily_limit(user_id, max_calls=2)
        count, _ = check_ai_daily_limit(user_id, max_calls=2)
        assert count == 3  # exceeds max_calls=2

    def test_different_users_are_isolated(self) -> None:
        from app.middleware.ai_rate_limit import check_ai_daily_limit

        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        check_ai_daily_limit(user_a, max_calls=2)
        check_ai_daily_limit(user_a, max_calls=2)
        count, _ = check_ai_daily_limit(user_b, max_calls=2)
        assert count == 1  # user_b unaffected by user_a's calls


# ---------------------------------------------------------------------------
# Integration tests — HTTP endpoints
# ---------------------------------------------------------------------------


class TestAIDailyRateLimitHTTP:
    def setup_method(self) -> None:
        _reset_ai_counter()

    @pytest.fixture(autouse=True)
    def _reset_after(self) -> None:
        yield
        _reset_ai_counter()

    def test_first_generate_returns_200_with_remaining_header(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "ai-rl-1st")
        _grant_premium(app, token)

        resp = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        assert resp.headers.get("X-AI-Calls-Remaining") == "0"

    def test_repeat_generate_same_period_returns_cached(self, app, client) -> None:
        token = _register_and_login(client, "ai-rl-2nd")
        _grant_premium(app, token)

        client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        resp = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token, v2=True),
        )

        # Semantic dedupe (#1546): the repeat serves the existing insight.
        assert resp.status_code == 200
        payload = resp.get_json()
        data = payload.get("data") or payload
        assert data["cached"] is True
        assert resp.headers.get("X-AI-Calls-Remaining") == "0"

    def test_force_regenerate_at_daily_limit_returns_429(self, app, client) -> None:
        token = _register_and_login(client, "ai-rl-3rd")
        _grant_premium(app, token)

        client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        resp = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily", "force_regenerate": True},
            headers=_auth(token, v2=True),
        )

        assert resp.status_code == 429
        data = resp.get_json()
        assert data["error"]["code"] == "AI_DAILY_LIMIT_EXCEEDED"
        assert "Retry-After" in resp.headers
        assert resp.headers.get("X-AI-Calls-Remaining") == "0"

    def test_provider_failure_does_not_consume_daily_limit(self, app, client) -> None:
        token = _register_and_login(client, "ai-rl-provider-fail")
        _grant_premium(app, token)

        from app.services.llm_provider import StubLLMProvider

        class _FlakyProvider(StubLLMProvider):
            _failed = False

            def generate_with_usage(
                self, prompt, *, response_schema=None, max_tokens=None
            ):
                if not _FlakyProvider._failed:
                    _FlakyProvider._failed = True
                    raise LLMProviderError("provider down")
                return super().generate_with_usage(
                    prompt,
                    response_schema=response_schema,
                    max_tokens=max_tokens,
                )

        with patch(
            "app.services.ai_advisory_service.get_llm_provider",
            return_value=_FlakyProvider(),
        ):
            failed = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily"},
                headers=_auth(token, v2=True),
            )
            recovered = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily"},
                headers=_auth(token),
            )

        assert failed.status_code == 500
        assert recovered.status_code == 200
        assert recovered.headers.get("X-AI-Calls-Remaining") == "0"

    def test_spending_read_is_free_and_never_blocks(self, app, client) -> None:
        """GET /ai/insights/spending is read-only (#1546): repeated reads never
        generate, never consume quota and never 429."""
        token = _register_and_login(client, "ai-rl-cached")
        _grant_premium(app, token)

        for _ in range(3):
            resp = client.get("/ai/insights/spending", headers=_auth(token))
            assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"

        # Quota untouched: a real generation still goes through.
        generate = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        assert generate.status_code == 200
        payload = generate.get_json()
        data = payload.get("data") or payload
        assert data["cached"] is False

    def test_cached_period_generate_does_not_consume_daily_limit(
        self, app, client
    ) -> None:
        token = _register_and_login(client, "ai-rl-generate-cached")
        _grant_premium(app, token)

        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService.generate_financial_insights",
            return_value={
                "period_type": "daily",
                "period_label": "2026-05-17",
                "period_start": "2026-05-17",
                "period_end": "2026-05-17",
                "summary": "cached",
                "items": [],
                "context_version": "financial_insight_snapshot.v1",
                "cached": True,
                "model": "stub",
                "tokens_used": 10,
                "cost_usd": 0.0,
            },
        ):
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily", "anchor_date": "2026-05-17"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        assert resp.headers.get("X-AI-Calls-Remaining") == "1"

    def test_429_message_is_portuguese(self, app, client) -> None:
        token = _register_and_login(client, "ai-rl-ptbr")
        _grant_premium(app, token)

        client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        resp = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily", "force_regenerate": True},
            headers=_auth(token, v2=True),
        )

        assert resp.status_code == 429
        data = resp.get_json()
        assert (
            "amanhã" in data.get("message", "").lower()
            or "amanhã" in str(data.get("error", {})).lower()
        )

    def test_weekly_summary_read_is_not_rate_limited(self, app, client) -> None:
        """The weekly-summary GET is read-only and must NOT consume the AI daily
        quota — generation (and its rate limit) lives in the scheduled batch."""
        token = _register_and_login(client, "ai-rl-weekly")
        _grant_premium(app, token)

        # Many reads in a row must keep returning 200, never 429.
        client.get("/ai/insights/weekly-summary", headers=_auth(token))
        client.get("/ai/insights/weekly-summary", headers=_auth(token))
        resp = client.get("/ai/insights/weekly-summary", headers=_auth(token, v2=True))

        assert resp.status_code == 200

    def test_weekly_read_does_not_consume_generate_counter(self, app, client) -> None:
        """The weekly-summary read is free; only generation consumes the daily
        counter, so a weekly read between two generate calls does not shift the
        limit."""
        token = _register_and_login(client, "ai-rl-shared")
        _grant_premium(app, token)

        r1 = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token),
        )
        r2 = client.get("/ai/insights/weekly-summary", headers=_auth(token, v2=True))
        r3 = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily", "force_regenerate": True},
            headers=_auth(token, v2=True),
        )

        assert r1.status_code == 200
        assert r2.status_code == 200  # read-only, not rate limited
        assert r3.status_code == 429  # forced second generation hits the daily cap

    def test_free_user_gets_403_not_429(self, app, client) -> None:
        """Free users are blocked by entitlement gate before reaching rate limit."""
        token = _register_and_login(client, "ai-rl-free")
        _revoke_premium(app, token)  # new users get trial; explicitly revoke

        for _ in range(3):
            resp = client.get("/ai/insights/spending", headers=_auth(token, v2=True))
        assert resp.status_code == 403
        assert resp.get_json().get("error", {}).get("code") == "ENTITLEMENT_REQUIRED"

    def test_rate_limit_isolated_per_user(self, app, client) -> None:
        token_a = _register_and_login(client, "ai-rl-isola")
        token_b = _register_and_login(client, "ai-rl-isolb")
        _grant_premium(app, token_a)
        _grant_premium(app, token_b)

        # Exhaust user_a (1/day → forced second generation blocked)
        client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token_a),
        )
        blocked = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily", "force_regenerate": True},
            headers=_auth(token_a, v2=True),
        )
        assert blocked.status_code == 429

        # user_b still has full quota
        resp_b = client.post(
            "/ai/insights/generate",
            json={"period_type": "daily"},
            headers=_auth(token_b),
        )
        assert resp_b.status_code == 200
        assert resp_b.headers.get("X-AI-Calls-Remaining") == "0"
