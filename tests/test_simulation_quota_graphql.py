"""Parity GraphQL da quota de simulação (freemium) — #1409."""

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


def _gql(client, token: str, query: str):
    return client.post(
        "/graphql",
        json={"query": query},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_simulation_quota_query(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "has_entitlement", lambda *_a, **_k: False)
    token = _register_and_login(client, prefix="gql-quota")
    resp = _gql(
        client,
        token,
        "query { simulationQuota { limit used remaining unlimited allowed resetAt } }",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "errors" not in body, body
    quota = body["data"]["simulationQuota"]
    assert quota["limit"] == 1
    assert quota["remaining"] == 1
    assert quota["unlimited"] is False
    assert quota["allowed"] is True


def test_consume_simulation_quota_mutation_then_paywall(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "has_entitlement", lambda *_a, **_k: False)
    token = _register_and_login(client, prefix="gql-consume")
    mutation = (
        "mutation { consumeSimulationQuota { quota { allowed remaining unlimited } } }"
    )

    first = _gql(client, token, mutation).get_json()
    assert "errors" not in first, first
    assert first["data"]["consumeSimulationQuota"]["quota"]["allowed"] is True

    second = _gql(client, token, mutation).get_json()
    quota = second["data"]["consumeSimulationQuota"]["quota"]
    assert quota["allowed"] is False
    assert quota["remaining"] == 0


def test_simulation_quota_requires_auth(client) -> None:
    out = client.post(
        "/graphql",
        json={"query": "query { simulationQuota { limit } }"},
    )
    body = out.get_json()
    assert body.get("errors"), body
