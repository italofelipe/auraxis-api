"""Integração REST da quota de simulação (freemium) — #1409."""

from __future__ import annotations

import uuid

import pytest

from app.application.services import simulation_quota_service as svc


def _register_and_login(client, *, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"
    reg = client.post(
        "/auth/register",
        json={"name": f"user-{suffix}", "email": email, "password": password},
    )
    assert reg.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.get_json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _data(resp) -> dict:
    """Lê o snapshot de quota tanto no contrato legacy (flat) quanto standard (data)."""
    body = resp.get_json()
    return body.get("data", body)


def test_get_quota_free(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "has_entitlement", lambda *_a, **_k: False)
    token = _register_and_login(client, prefix="quota-get")
    resp = client.get("/simulations/quota", headers=_auth(token))
    assert resp.status_code == 200
    data = _data(resp)
    assert data["limit"] == 1
    assert data["remaining"] == 1
    assert data["unlimited"] is False
    assert data["allowed"] is True


def test_consume_free_then_paywall(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "has_entitlement", lambda *_a, **_k: False)
    token = _register_and_login(client, prefix="quota-consume")

    first = client.post("/simulations/quota/consume", headers=_auth(token))
    assert first.status_code == 200
    assert _data(first)["allowed"] is True

    second = client.post("/simulations/quota/consume", headers=_auth(token))
    assert second.status_code == 200  # sem erro HTTP — paywall é decisão do client
    body = _data(second)
    assert body["allowed"] is False
    assert body["remaining"] == 0


def test_premium_unlimited(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "has_entitlement", lambda *_a, **_k: True)
    token = _register_and_login(client, prefix="quota-premium")

    snapshot = _data(client.get("/simulations/quota", headers=_auth(token)))
    assert snapshot["unlimited"] is True
    assert snapshot["remaining"] is None

    for _ in range(3):
        consumed = _data(
            client.post("/simulations/quota/consume", headers=_auth(token))
        )
        assert consumed["allowed"] is True
        assert consumed["unlimited"] is True


def test_quota_requires_auth(client) -> None:
    assert client.get("/simulations/quota").status_code == 401
    assert client.post("/simulations/quota/consume").status_code == 401
