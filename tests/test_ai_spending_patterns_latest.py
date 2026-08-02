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


def _seed_expense(
    app,
    user_id: _uuid.UUID,
    *,
    amount: str = "42.90",
    due_date: date | None = None,
    category: str | None = "alimentacao",
) -> None:
    """Insert one EXPENSE inside the radar's 90-day window."""
    from decimal import Decimal

    from app.extensions.database import db
    from app.models.transaction import (
        Transaction,
        TransactionCategory,
        TransactionType,
    )

    with app.app_context():
        db.session.add(
            Transaction(
                user_id=user_id,
                title="Cafeteria",
                amount=Decimal(amount),
                type=TransactionType.EXPENSE,
                due_date=due_date or (date(2026, 6, 5) - timedelta(days=3)),
                category=TransactionCategory(category) if category else None,
            )
        )
        db.session.commit()


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


def test_generate_mints_service_token(app, client, monkeypatch) -> None:
    """The cron mints a token_use=service token so v2 skips per-user session
    (active_jti) revocation for the internal call. Regression for #1596."""
    from flask_jwt_extended import decode_token

    token = _register_and_login(client)
    user_id = _grant_premium(app, token)
    _seed_expense(app, user_id)

    captured: dict[str, str] = {}

    def _capture(*, transactions, period_days, auth_header):  # noqa: ANN001
        captured["auth_header"] = auth_header
        return 200, {"patterns": []}

    monkeypatch.setattr(sps_service, "call_v2_spending_patterns", _capture)

    with app.app_context():
        sps_service.generate_and_persist_spending_patterns(
            user_id, anchor_date=date(2026, 6, 5)
        )
        service_token = captured["auth_header"].removeprefix("Bearer ")
        decoded = decode_token(service_token)
        assert decoded["token_use"] == "service"
        assert decoded["sub"] == str(user_id)


def test_generate_persists_insight(app, client, monkeypatch) -> None:
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)
    _seed_expense(app, user_id)

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
    _seed_expense(app, user_id)

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
    _seed_expense(app, user_id)

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
# #1596 — the weekly cron failed for 8 days with an unreadable error
# ---------------------------------------------------------------------------


def test_generate_skips_v2_when_user_has_no_expenses(app, client, monkeypatch) -> None:
    """A Premium user with no expenses in the window must not hit v2.

    v2 declares ``transactions: min_length=1``; posting an empty list earns a
    422 that v1 used to surface as a generic "Falha ao gerar o radar de gastos.",
    turning "nothing to analyse" into a red weekly job. Regression for #1596.
    """
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)

    def _boom(**_kwargs):  # noqa: ANN003
        raise AssertionError("v2 must not be called with an empty payload")

    monkeypatch.setattr(sps_service, "call_v2_spending_patterns", _boom)

    with app.app_context():
        result = sps_service.generate_and_persist_spending_patterns(
            user_id, anchor_date=date(2026, 6, 5)
        )

    assert result["persisted"] is False
    assert result["patterns"] == []


def test_generate_drops_amounts_v2_would_reject(app, client, monkeypatch) -> None:
    """v2 declares ``amount: float = Field(gt=0)``.

    One zeroed row used to 422 the whole user; filter it out instead.
    """
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)
    _seed_expense(app, user_id, amount="0.00")
    _seed_expense(app, user_id, amount="42.90")

    captured: dict[str, object] = {}

    def _capture(*, transactions, period_days, auth_header):  # noqa: ANN001
        captured["transactions"] = transactions
        return 200, {"patterns": []}

    monkeypatch.setattr(sps_service, "call_v2_spending_patterns", _capture)

    with app.app_context():
        sps_service.generate_and_persist_spending_patterns(
            user_id, anchor_date=date(2026, 6, 5)
        )

    forwarded = captured["transactions"]
    assert [row["amount"] for row in forwarded] == [42.90]


def test_upstream_error_names_the_status_and_detail(app, client, monkeypatch) -> None:
    """The cron's only output is ``error={exc}`` — it must name the cause.

    #1596 stayed open for 8 days because a 401 ``Token revoked.`` from v2 was
    indistinguishable from a 422 or a 500 in the job log and in the auto-opened
    issue.
    """
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)
    _seed_expense(app, user_id)

    _patch_v2(monkeypatch, status=401, body={"detail": "Token revoked."})

    with app.app_context():
        try:
            sps_service.generate_and_persist_spending_patterns(
                user_id, anchor_date=date(2026, 6, 5)
            )
        except sps_service.SpendingPatternsUpstreamError as exc:
            assert exc.status_code == 401
            assert "401" in str(exc)
            assert "Token revoked." in str(exc)
        else:  # pragma: no cover - guard
            raise AssertionError("expected SpendingPatternsUpstreamError")


def test_upstream_error_never_echoes_validation_input(app, client, monkeypatch) -> None:
    """A 422 body carries the rejected ``input`` — amounts are user data (LGPD).

    Report the field location and the error type, never the value.
    """
    token = _register_and_login(client)
    user_id = _grant_premium(app, token)
    _seed_expense(app, user_id)

    _patch_v2(
        monkeypatch,
        status=422,
        body={
            "detail": [
                {
                    "type": "greater_than",
                    "loc": ["body", "transactions", 0, "amount"],
                    "msg": "Input should be greater than 0",
                    "input": "1234.56",
                }
            ]
        },
    )

    with app.app_context():
        try:
            sps_service.generate_and_persist_spending_patterns(
                user_id, anchor_date=date(2026, 6, 5)
            )
        except sps_service.SpendingPatternsUpstreamError as exc:
            message = str(exc)
            assert "422" in message
            assert "greater_than" in message
            assert "transactions.0.amount" in message
            assert "1234.56" not in message
        else:  # pragma: no cover - guard
            raise AssertionError("expected SpendingPatternsUpstreamError")


def test_describe_upstream_failure_degrades_to_the_status_alone() -> None:
    """An unparseable body must still yield a message that names the status."""
    describe = sps_service._describe_upstream_failure

    assert describe(502, {}) == "HTTP 502"
    assert describe(500, {"error": "boom"}) == "HTTP 500"
    assert describe(422, {"detail": ["not-a-dict"]}) == "HTTP 422"
    assert describe(422, {"detail": [{"loc": [], "type": "missing"}]}) == (
        "HTTP 422: missing"
    )
    assert describe(422, {"detail": [{"loc": ["body"]}]}) == "HTTP 422: invalid"


def test_cli_counts_user_without_expenses_as_skipped(app, client, monkeypatch) -> None:
    """No expenses is not a failure — the weekly job must stay green."""
    token = _register_and_login(client)
    _grant_premium(app, token)

    def _boom(**_kwargs):  # noqa: ANN003
        raise AssertionError("v2 must not be called with an empty payload")

    monkeypatch.setattr(sps_service, "call_v2_spending_patterns", _boom)

    result = _invoke_cli(app)
    assert result.exit_code == 0, result.output
    assert "failures=0" in result.output
    assert "skipped=1" in result.output


# ---------------------------------------------------------------------------
# CLI — flask ai spending-patterns
# ---------------------------------------------------------------------------


def _brt_today() -> date:
    from app.cli.ai_insights_cli import _brt_today as _impl

    return _impl()


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
    _seed_expense(app, user_id, due_date=_brt_today() - timedelta(days=3))

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
