"""Testes do simulation_quota_service (freemium simulador) — #1409."""

from __future__ import annotations

from typing import Any

import pytest

from app.application.services import simulation_quota_service as svc
from app.extensions.database import db
from app.models.simulation_quota_usage import SimulationQuotaUsage
from app.models.user import User


def _make_user(email: str) -> User:
    user = User(name="quota-user", email=email, password="hash")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def _free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "has_entitlement", lambda *_a, **_k: False)


@pytest.fixture
def _premium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "has_entitlement", lambda *_a, **_k: True)


def test_get_quota_free_initial(app: Any, _free: None) -> None:
    with app.app_context():
        user = _make_user("q1@email.com")
        quota = svc.get_quota(user.id)
        assert quota["limit"] == 1
        assert quota["used"] == 0
        assert quota["remaining"] == 1
        assert quota["unlimited"] is False
        assert quota["allowed"] is True
        assert quota["reset_at"].endswith("Z")


def test_consume_free_first_then_exhausted(app: Any, _free: None) -> None:
    with app.app_context():
        user = _make_user("q2@email.com")

        first = svc.consume(user.id)
        assert first["allowed"] is True
        assert first["used"] == 1
        assert first["remaining"] == 0

        second = svc.consume(user.id)
        assert second["allowed"] is False
        assert second["used"] == 1  # não incrementa além do limite
        assert second["remaining"] == 0

        rows = SimulationQuotaUsage.query.filter_by(user_id=user.id).all()
        assert len(rows) == 1
        assert rows[0].count == 1


def test_premium_is_unlimited_and_creates_no_row(app: Any, _premium: None) -> None:
    with app.app_context():
        user = _make_user("q3@email.com")

        quota = svc.get_quota(user.id)
        assert quota["unlimited"] is True
        assert quota["remaining"] is None
        assert quota["allowed"] is True

        for _ in range(3):
            consumed = svc.consume(user.id)
            assert consumed["unlimited"] is True
            assert consumed["allowed"] is True

        assert SimulationQuotaUsage.query.filter_by(user_id=user.id).count() == 0


def test_get_quota_reflects_existing_usage(app: Any, _free: None) -> None:
    with app.app_context():
        user = _make_user("q4@email.com")
        period = svc._current_period()
        db.session.add(SimulationQuotaUsage(user_id=user.id, period=period, count=1))
        db.session.commit()

        quota = svc.get_quota(user.id)
        assert quota["used"] == 1
        assert quota["remaining"] == 0
        assert quota["allowed"] is False


def test_period_isolation_resets_next_month(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "has_entitlement", lambda *_a, **_k: False)
    with app.app_context():
        user = _make_user("q5@email.com")

        monkeypatch.setattr(svc, "_current_period", lambda *_a, **_k: "2026-05")
        assert svc.consume(user.id)["allowed"] is True
        assert svc.consume(user.id)["allowed"] is False

        # Vira o mês → novo período → quota zerada de novo.
        monkeypatch.setattr(svc, "_current_period", lambda *_a, **_k: "2026-06")
        assert svc.get_quota(user.id)["remaining"] == 1
        assert svc.consume(user.id)["allowed"] is True


def test_next_reset_handles_december_rollover() -> None:
    from datetime import datetime

    reset = svc._next_reset_at(datetime(2026, 12, 15))
    assert reset.startswith("2027-01-01")
