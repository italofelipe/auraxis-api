"""Tests for the spending-patterns gateway proxy (PROD-04, #567).

The proxy forwards POST /ai/insights/spending-patterns to auraxis-api-v2 after
enforcing the premium entitlement. v2 itself is mocked here — these tests cover
the gateway behaviour (entitlement gate, v2-unconfigured, forwarding, upstream
failure), not the LLM.
"""

from __future__ import annotations

import uuid as _uuid

import requests

from app.controllers.ai import spending_patterns_proxy

_PAYLOAD = {
    "transactions": [
        {"amount": 12.5, "occurred_on": "2026-05-01", "category": "food"},
    ],
    "period_days": 90,
}


def _register_and_login(client) -> tuple[str, str]:
    suffix = _uuid.uuid4().hex[:8]
    email = f"sp-proxy-{suffix}@test.com"
    password = "StrongPass@123"
    reg = client.post(
        "/auth/register",
        json={"name": f"sp-{suffix}", "email": email, "password": password},
    )
    assert reg.status_code == 201, reg.get_json()
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.get_json()
    return login.get_json()["token"], email


def _grant_premium(app, token: str) -> None:
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


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_returns_403_without_entitlement(app, client, monkeypatch) -> None:
    monkeypatch.setenv("AURAXIS_API_V2_BASE_URL", "https://v2.test")
    token, _ = _register_and_login(client)
    # Fresh users get a trial entitlement; revoke it to exercise the gate.
    from flask_jwt_extended import decode_token

    from app.services.entitlement_service import deactivate_premium

    with app.app_context():
        deactivate_premium(_uuid.UUID(decode_token(token)["sub"]))
    resp = client.post(
        "/ai/insights/spending-patterns",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
    )
    assert resp.status_code == 403
    error = (resp.get_json() or {}).get("error", {})
    assert error.get("code") == "ENTITLEMENT_REQUIRED"


def test_returns_503_when_v2_unconfigured(app, client, monkeypatch) -> None:
    monkeypatch.delenv("AURAXIS_API_V2_BASE_URL", raising=False)
    token, _ = _register_and_login(client)
    _grant_premium(app, token)
    resp = client.post(
        "/ai/insights/spending-patterns",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
    )
    assert resp.status_code == 503
    error = (resp.get_json() or {}).get("error", {})
    assert error.get("code") == "SERVICE_UNAVAILABLE"


def test_forwards_to_v2_and_returns_patterns(app, client, monkeypatch) -> None:
    monkeypatch.setenv("AURAXIS_API_V2_BASE_URL", "https://v2.test")
    captured: dict = {}

    def _fake_post(url, json, headers, timeout):  # noqa: A002 — mirror requests kwarg
        captured["url"] = url
        captured["json"] = json
        captured["auth"] = headers.get("Authorization")
        return _FakeResponse(
            200,
            {
                "patterns": [{"description": "Cafés", "severity": "high"}],
                "model": "stub",
                "generated_count": 1,
            },
        )

    monkeypatch.setattr(spending_patterns_proxy.requests, "post", _fake_post)
    token, _ = _register_and_login(client)
    _grant_premium(app, token)

    resp = client.post(
        "/ai/insights/spending-patterns",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
    )
    assert resp.status_code == 200, resp.get_json()
    assert captured["url"] == "https://v2.test/v2/insights/spending-patterns"
    assert captured["auth"] == f"Bearer {token}"
    body = resp.get_json() or {}
    data = body.get("data") or body
    assert data["generated_count"] == 1


def test_returns_503_when_v2_unreachable(app, client, monkeypatch) -> None:
    monkeypatch.setenv("AURAXIS_API_V2_BASE_URL", "https://v2.test")

    def _boom(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(spending_patterns_proxy.requests, "post", _boom)
    token, _ = _register_and_login(client)
    _grant_premium(app, token)

    resp = client.post(
        "/ai/insights/spending-patterns",
        json=_PAYLOAD,
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
    )
    assert resp.status_code == 503
