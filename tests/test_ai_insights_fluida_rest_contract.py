"""End-to-end REST contract test for the Fluida fields (#1501).

Drives ``POST /ai/insights/generate`` through the real HTTP stack with a stubbed
LLM provider and asserts the response carries the structured Fluida fields while
keeping every pre-existing contract key (no regression).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm_provider import LLMResponse


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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def _seed_expense(app, user_id: uuid.UUID, *, amount: str, due_date: date) -> None:
    with app.app_context():
        from app.extensions.database import db
        from app.models.transaction import (
            Transaction,
            TransactionStatus,
            TransactionType,
        )

        db.session.add(
            Transaction(
                user_id=user_id,
                title="gasto",
                description="gasto",
                amount=Decimal(amount),
                type=TransactionType.EXPENSE,
                status=TransactionStatus.PAID,
                due_date=due_date,
            )
        )
        db.session.commit()


def _financial_llm_response() -> LLMResponse:
    item = (
        '{"type":"saude_financeira","dimension":"general","title":"Item",'
        '"message":"Os dados foram analisados.",'
        '"evidence":["current_period.paid.balance"]}'
    )
    return LLMResponse(
        content=f'{{"summary":"Resumo do dia.","items":[{item}]}}',
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        model="gpt-4o-mini",
        latency_ms=120,
    )


@pytest.fixture(autouse=True)
def _reset_ai_counter():
    from app.middleware.ai_rate_limit import _InMemoryAICounter

    _InMemoryAICounter.reset()
    yield
    _InMemoryAICounter.reset()


_LEGACY_KEYS = {
    "id",
    "period_type",
    "period_label",
    "period_start",
    "period_end",
    "summary",
    "items",
    "context_version",
    "cached",
    "model",
    "tokens_used",
    "cost_usd",
}
_FLUIDA_KEYS = {"paragraphs", "retro", "series", "highlights"}


class TestGenerateEndpointFluidaContract:
    def test_response_carries_fluida_and_legacy_keys(self, app, client) -> None:
        token = _register_and_login(client, "fluida-rest")
        user_id = _grant_premium(app, token)
        _seed_expense(app, user_id, amount="42.00", due_date=date(2026, 6, 14))

        provider = MagicMock()
        provider.generate_with_usage.return_value = _financial_llm_response()

        with patch(
            "app.services.ai_advisory_service.get_llm_provider",
            return_value=provider,
        ):
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily", "anchor_date": "2026-06-15"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data", body)

        # No contract regression.
        assert _LEGACY_KEYS <= set(data), sorted(_LEGACY_KEYS - set(data))
        # New structured fields present and well-formed.
        assert _FLUIDA_KEYS <= set(data)
        assert isinstance(data["paragraphs"], list)
        assert len(data["series"]["daily"]) == 7
        assert len(data["series"]["weekly"]) == 6
        retro = {e["key"]: e for e in data["retro"]}
        assert retro["yesterday"]["value"] == 42.0

    def test_response_carries_editorial_lead(self, app, client) -> None:
        token = _register_and_login(client, "fluida-lead-rest")
        user_id = _grant_premium(app, token)
        _seed_expense(app, user_id, amount="42.00", due_date=date(2026, 6, 14))

        provider = MagicMock()
        provider.generate_with_usage.return_value = _financial_llm_response()

        with patch(
            "app.services.ai_advisory_service.get_llm_provider",
            return_value=provider,
        ):
            resp = client.post(
                "/ai/insights/generate",
                json={"period_type": "daily", "anchor_date": "2026-06-15"},
                headers=_auth(token),
            )

        assert resp.status_code == 200
        body = resp.get_json()
        data = body.get("data", body)
        assert "lead" in data
        lead = data["lead"]
        assert set(lead) == {"severity", "read_min", "title", "lead", "next_step"}
        # Daily general reading time, derived title from the stubbed summary.
        assert lead["read_min"] == 15
        assert lead["severity"] in {"ok", "attention", "alert"}
        assert lead["title"] == "Resumo do dia."
