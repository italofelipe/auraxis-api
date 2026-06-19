"""Tests for the cached Radar de Gastos (spending-patterns) feature (#1455).

Covers:
  * GET /ai/insights/spending-patterns/latest is read-only and does NOT consume
    the AI daily quota (two consecutive calls never 429).
  * read_latest_spending_patterns with and without cached data.
  * generate_and_persist_spending_patterns with v2 mocked (persists an AIInsight).
  * flask ai spending-patterns CLI: dry-run + a real run with v2 mocked.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import date, timedelta

from click.testing import CliRunner

from app.services import ai_spending_patterns_service as sps_service

# The v2 contract envelope ({"data": ...} / {"error": {"code": ...}}) is opted
# into via this header; without it the legacy flat payload is returned.
_V2 = {"X-API-Contract": "v2"}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **_V2}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(client) -> str:
    suffix = _uuid.uuid4().hex[:8]
    email = f"sp-latest-{suffix}@test.com"
    password = "StrongPass@123"
    reg = client.post(
        "/auth/register",
        json={"name": f"sp-{suffix}", "email": email, "password": password},
    )
    assert reg.status_code == 201, reg.get_json()
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.get_json()
    return login.get_json()["token"]


def _grant_premium(app, token: str) -> _uuid.UUID:
    from flask_jwt_extended import decode_token

    from app.extensions.database import db
    from app.models.entitlement import Entitlement, EntitlementSource

    with app.app_context():
        user_id = _uuid.UUID(decode_token(token)["sub"])
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


def _seed_cached_radar(app, user_id: _uuid.UUID, *, period_label: str) -> None:
    from app.extensions.database import db
    from app.models.ai_insight import AIInsight, InsightType

    with app.app_context():
        anchor = date.fromisoformat(period_label)
        db.session.add(
            AIInsight(
                user_id=user_id,
                content='{"patterns":[{"description":"Cafés","severity":"high"}]}',
                insight_type=InsightType.spending_patterns,
                period_label=period_label,
                period_start=anchor - timedelta(days=90),
                period_end=anchor,
                model="v2-spending-patterns",
                tokens_used=280,
                cost_usd=0.000042,
            )
        )
        db.session.commit()


# ---------------------------------------------------------------------------
# Endpoint — read-only / no quota
# ---------------------------------------------------------------------------


def test_latest_requires_premium(app, client) -> None:
    token = _register_and_login(client)
    from flask_jwt_extended import decode_token

    from app.services.entitlement_service import deactivate_premium

    with app.app_context():
        deactivate_premium(_uuid.UUID(decode_token(token)["sub"]))

    resp = client.get(
        "/ai/insights/spending-patterns/latest",
        headers=_auth(token),
    )
    assert resp.status_code == 403
    assert (resp.get_json() or {}).get("error", {}).get(
        "code"
    ) == "ENTITLEMENT_REQUIRED"


def test_latest_empty_when_no_cache(app, client) -> None:
    token = _register_and_login(client)
    _grant_premium(app, token)

    resp = client.get(
        "/ai/insights/spending-patterns/latest",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json() or {}
    data = body.get("data") or body
    assert data["patterns"] == []
    assert data["generated_at"] is None


def test_latest_returns_cached_radar(app, client) -> None:
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)
    _seed_cached_radar(app, user_id, period_label="2026-06-05")

    resp = client.get(
        "/ai/insights/spending-patterns/latest",
        headers=_auth(token),
    )
    assert resp.status_code == 200, resp.get_json()
    data = (resp.get_json() or {}).get("data") or {}
    assert data["patterns"] == [{"description": "Cafés", "severity": "high"}]
    assert data["period_label"] == "2026-06-05"
    assert data["generated_at"] is not None


def test_latest_does_not_consume_daily_quota(app, client) -> None:
    """Two consecutive reads must both succeed — the endpoint has no @ai_daily_limit."""
    token = _register_and_login(client)
    _grant_premium(app, token)

    headers = _auth(token)
    first = client.get("/ai/insights/spending-patterns/latest", headers=headers)
    second = client.get("/ai/insights/spending-patterns/latest", headers=headers)

    assert first.status_code == 200, first.get_json()
    assert second.status_code == 200, second.get_json()
    assert second.status_code != 429


# ---------------------------------------------------------------------------
# Service — read_latest_spending_patterns
# ---------------------------------------------------------------------------


def test_read_latest_returns_empty_without_data(app, client) -> None:
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)

    with app.app_context():
        result = sps_service.read_latest_spending_patterns(user_id)

    assert result == {
        "patterns": [],
        "generated_at": None,
        "period_label": None,
        "model": "",
        "cost_usd": 0.0,
        "tokens_used": 0,
    }


def test_read_latest_returns_cached(app, client) -> None:
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)
    _seed_cached_radar(app, user_id, period_label="2026-06-04")

    with app.app_context():
        result = sps_service.read_latest_spending_patterns(user_id)

    assert result["patterns"] == [{"description": "Cafés", "severity": "high"}]
    assert result["period_label"] == "2026-06-04"
    assert result["tokens_used"] == 280


# ---------------------------------------------------------------------------
# Service — generate_and_persist_spending_patterns (v2 mocked)
# ---------------------------------------------------------------------------


def _patch_v2(monkeypatch, *, status: int, body: dict) -> None:
    def _fake_call(*, transactions, period_days, auth_header):  # noqa: ANN001
        assert period_days == 90
        assert auth_header.startswith("Bearer ")
        return status, body

    monkeypatch.setattr(sps_service, "call_v2_spending_patterns", _fake_call)


def test_generate_persists_insight(app, client, monkeypatch) -> None:
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)

    _patch_v2(
        monkeypatch,
        status=200,
        body={
            "patterns": [{"description": "Delivery", "severity": "medium"}],
            "model": "stub",
            "cost_usd": 0.0001,
            "tokens_used": 120,
        },
    )

    with app.app_context():
        result = sps_service.generate_and_persist_spending_patterns(
            user_id, anchor_date=date(2026, 6, 5)
        )
        assert result["persisted"] is True
        assert result["patterns"] == [{"description": "Delivery", "severity": "medium"}]

        latest = sps_service.read_latest_spending_patterns(user_id)
        assert latest["patterns"] == [{"description": "Delivery", "severity": "medium"}]
        assert latest["period_label"] == "2026-06-05"
        assert latest["model"] == "stub"
        assert latest["tokens_used"] == 120


def test_generate_does_not_persist_when_empty(app, client, monkeypatch) -> None:
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)

    _patch_v2(monkeypatch, status=200, body={"patterns": []})

    with app.app_context():
        result = sps_service.generate_and_persist_spending_patterns(
            user_id, anchor_date=date(2026, 6, 5)
        )
        assert result["persisted"] is False
        assert result["patterns"] == []
        assert sps_service.read_latest_spending_patterns(user_id)["patterns"] == []


def test_generate_raises_on_upstream_error(app, client, monkeypatch) -> None:
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)

    _patch_v2(monkeypatch, status=502, body={"error": "boom"})

    with app.app_context():
        try:
            sps_service.generate_and_persist_spending_patterns(
                user_id, anchor_date=date(2026, 6, 5)
            )
        except sps_service.SpendingPatternsUpstreamError as exc:
            assert exc.status_code == 502
        else:  # pragma: no cover - guard
            raise AssertionError("expected SpendingPatternsUpstreamError")


# ---------------------------------------------------------------------------
# CLI — flask ai spending-patterns
# ---------------------------------------------------------------------------


def _invoke_cli(app, *args: str) -> object:
    from app.cli.ai_insights_cli import ai_insights_cli

    runner = CliRunner()
    with app.app_context():
        return runner.invoke(ai_insights_cli, ["spending-patterns", *args])


def test_cli_dry_run_does_not_call_v2(app, client, monkeypatch) -> None:
    token = _register_and_login(client)
    _grant_premium(app, token)

    called = {"n": 0}

    def _boom(**_kwargs):  # noqa: ANN003
        called["n"] += 1
        raise AssertionError("v2 must not be called on dry-run")

    monkeypatch.setattr(sps_service, "call_v2_spending_patterns", _boom)

    result = _invoke_cli(app, "--dry-run")
    assert result.exit_code == 0
    assert "dry-run" in result.output.lower()
    assert called["n"] == 0


def test_cli_generates_for_premium_user(app, client, monkeypatch) -> None:
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)

    _patch_v2(
        monkeypatch,
        status=200,
        body={
            "patterns": [{"description": "Apps", "severity": "high"}],
            "model": "stub",
            "cost_usd": 0.0002,
            "tokens_used": 90,
        },
    )

    result = _invoke_cli(app)
    assert result.exit_code == 0, result.output
    assert "processed=1" in result.output
    assert "failures=0" in result.output

    with app.app_context():
        latest = sps_service.read_latest_spending_patterns(user_id)
        assert latest["patterns"] == [{"description": "Apps", "severity": "high"}]


def test_cli_idempotent_skips_when_cached_today(app, client, monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone

    token = _register_and_login(client)
    user_id = _grant_premium(app, token)
    today = datetime.now(timezone(timedelta(hours=-3))).date()
    _seed_cached_radar(app, user_id, period_label=today.isoformat())

    def _boom(**_kwargs):  # noqa: ANN003
        raise AssertionError("v2 must not be called when already cached today")

    monkeypatch.setattr(sps_service, "call_v2_spending_patterns", _boom)

    result = _invoke_cli(app)
    assert result.exit_code == 0
    assert "skipped=1" in result.output


def test_cli_no_premium_users_exits_zero(app) -> None:
    result = _invoke_cli(app)
    assert result.exit_code == 0
    assert "processed=0" in result.output
