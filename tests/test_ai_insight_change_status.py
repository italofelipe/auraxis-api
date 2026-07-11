"""Change-status detection for AI insights (#1482).

`GET /ai/insights/change-status` (and the GraphQL `aiInsightChangeStatus` query)
report whether the financial snapshot changed since the last persisted insight,
without ever calling the LLM — no token cost, no quota consumption. The web app
uses it to show a "nothing changed — generate anyway?" confirmation modal.
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock

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
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


def _get_current_user_id(app, token: str) -> uuid.UUID:
    with app.app_context():
        from flask_jwt_extended import decode_token

        return uuid.UUID(decode_token(token)["sub"])


def _financial_llm_response(*, summary: str = "Resumo.") -> LLMResponse:
    dims = [
        ("general", "current_period.paid.balance"),
        ("transactions", "transactions.included_count"),
        ("credit_cards", "data_quality.domain_presence.credit_cards"),
        ("goals", "data_quality.domain_presence.goals"),
        ("budgets", "data_quality.domain_presence.budgets"),
        ("wallet", "data_quality.domain_presence.wallet"),
    ]
    payload_items = ",".join(
        (
            '{"type":"saude_financeira",'
            f'"dimension":"{dim}",'
            '"title":"Item",'
            '"message":"Os dados foram analisados.",'
            f'"evidence":["{evidence}"]}}'
        )
        for dim, evidence in dims
    )
    return LLMResponse(
        content=f'{{"summary":"{summary}","items":[{payload_items}]}}',
        prompt_tokens=100,
        completion_tokens=40,
        total_tokens=140,
        model="gpt-4o-mini",
        latency_ms=120,
    )


def _generate_daily(app, user_id: uuid.UUID, anchor: date) -> None:
    from app.services.ai_advisory_service import AIAdvisoryService

    provider = MagicMock()
    provider.generate_with_usage.return_value = _financial_llm_response()
    service = AIAdvisoryService(user_id=user_id, llm_provider=provider)
    # trigger="scheduled" skips the user-facing entitlement/quota gates (#1546)
    # — these tests exercise snapshot/hash logic with a raw uuid user.
    service.generate_financial_insights(
        period_type="daily", anchor_date=anchor, trigger="scheduled"
    )


class TestChangeStatusService:
    def test_changed_true_when_no_prior_insight(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            service = AIAdvisoryService(user_id=uuid.uuid4())
            result = service.financial_insight_change_status(
                period_type="daily",
                anchor_date=date(2026, 5, 17),
            )

            assert result["changed"] is True
            assert result["last_generated_at"] is None
            assert result["last_context_hash"] is None
            assert result["current_context_hash"]
            assert result["period_label"] == "2026-05-17"

    def test_changed_false_after_generation_when_unchanged(self, app) -> None:
        with app.app_context():
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            anchor = date(2026, 5, 17)
            _generate_daily(app, user_id, anchor)

            service = AIAdvisoryService(user_id=user_id)
            result = service.financial_insight_change_status(
                period_type="daily",
                anchor_date=anchor,
            )

            assert result["changed"] is False
            assert result["last_generated_at"] is not None
            assert result["last_context_hash"] == result["current_context_hash"]

    def test_changed_true_when_stored_hash_differs(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.ai_insight import AIInsight
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            anchor = date(2026, 5, 17)
            _generate_daily(app, user_id, anchor)

            saved = db.session.query(AIInsight).filter_by(user_id=user_id).one()
            saved.metadata_dict = {
                "context_schema_version": "financial_insight_snapshot.v1",
                "context_hash": "deadbeef-stale-hash",
            }
            db.session.commit()

            service = AIAdvisoryService(user_id=user_id)
            result = service.financial_insight_change_status(
                period_type="daily",
                anchor_date=anchor,
            )

            assert result["changed"] is True
            assert result["last_context_hash"] == "deadbeef-stale-hash"
            assert result["current_context_hash"] != "deadbeef-stale-hash"

    def test_change_status_does_not_call_llm_or_log_cost(self, app) -> None:
        with app.app_context():
            from app.extensions.database import db
            from app.models.llm_audit_log import LLMAuditLog
            from app.services.ai_advisory_service import AIAdvisoryService

            user_id = uuid.uuid4()
            before = db.session.query(LLMAuditLog).filter_by(user_id=user_id).count()

            service = AIAdvisoryService(user_id=user_id)
            service.financial_insight_change_status(
                period_type="daily",
                anchor_date=date(2026, 5, 17),
            )

            after = db.session.query(LLMAuditLog).filter_by(user_id=user_id).count()
            assert after == before  # no LLM call → no audit row


class TestChangeStatusEndpoint:
    def test_get_returns_changed_payload(self, app, client) -> None:
        token = _register_and_login(client, "change-status")
        user_id = _get_current_user_id(app, token)
        anchor = date(2026, 5, 17)
        with app.app_context():
            _generate_daily(app, user_id, anchor)

        resp = client.get(
            "/ai/insights/change-status?period_type=daily&anchor_date=2026-05-17",
            headers=_auth(token),
        )

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["changed"] is False
        assert data["period_type"] == "daily"
        assert data["period_label"] == "2026-05-17"

    def test_get_rejects_invalid_period_type(self, app, client) -> None:
        token = _register_and_login(client, "change-status-bad")
        resp = client.get(
            "/ai/insights/change-status?period_type=hourly",
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_get_rejects_invalid_anchor_date(self, app, client) -> None:
        token = _register_and_login(client, "change-status-anchor")
        resp = client.get(
            "/ai/insights/change-status?period_type=daily&anchor_date=not-a-date",
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_get_requires_auth(self, app, client) -> None:
        resp = client.get("/ai/insights/change-status?period_type=daily")
        assert resp.status_code == 401

    def test_get_without_anchor_uses_today_and_timezone(self, app, client) -> None:
        token = _register_and_login(client, "change-status-tz")
        resp = client.get(
            "/ai/insights/change-status?period_type=daily",
            headers={**_auth(token), "X-Auraxis-Timezone": "America/Sao_Paulo"},
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        # No insight exists for today → changed is True.
        assert data["changed"] is True
        assert data["last_generated_at"] is None

    def test_get_maps_service_error_to_500(self, app, client) -> None:
        from unittest.mock import patch

        token = _register_and_login(client, "change-status-err")
        with patch(
            "app.services.ai_advisory_service.AIAdvisoryService."
            "financial_insight_change_status",
            side_effect=RuntimeError("boom"),
        ):
            resp = client.get(
                "/ai/insights/change-status?period_type=daily&anchor_date=2026-05-17",
                headers=_auth(token),
            )
        assert resp.status_code == 500
        assert resp.get_json()["error"]["code"] == "INTERNAL_ERROR"


class TestChangeStatusGraphQL:
    def test_query_returns_changed(self, app, client) -> None:
        token = _register_and_login(client, "change-status-gql")
        user_id = _get_current_user_id(app, token)
        anchor = date(2026, 5, 17)
        with app.app_context():
            _generate_daily(app, user_id, anchor)

        query = """
            query($p: String!, $a: String) {
              aiInsightChangeStatus(periodType: $p, anchorDate: $a) {
                changed
                periodType
                periodLabel
                currentContextHash
                lastContextHash
              }
            }
        """
        resp = client.post(
            "/graphql",
            json={"query": query, "variables": {"p": "daily", "a": "2026-05-17"}},
            headers=_auth(token),
        )

        assert resp.status_code == 200
        payload = resp.get_json()["data"]["aiInsightChangeStatus"]
        assert payload["changed"] is False
        assert payload["periodLabel"] == "2026-05-17"
        assert payload["currentContextHash"] == payload["lastContextHash"]
