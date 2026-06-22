"""GraphQL parity tests for generateAiInsight mutation (MVP-3)."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID, uuid4


def _register_and_login(client, *, prefix: str) -> str:
    suffix = uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"
    register = client.post(
        "/auth/register",
        json={"name": f"user-{suffix}", "email": email, "password": password},
    )
    assert register.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    return login.get_json()["token"]


def _gql(client, query, token=None, variables=None, extra_headers=None):
    headers = {"Content-Type": "application/json", "X-API-Contract": "v2"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )


_GENERATE_MUTATION = """
mutation Gen($periodType: String!, $anchorDate: String) {
  generateAiInsight(periodType: $periodType, anchorDate: $anchorDate) {
    ok
    id
    periodType
    summary
    items { type dimension title message evidence }
    cached
    model
    forecast
  }
}
"""


class TestGenerateAiInsightMutation:
    def test_rejects_invalid_period_type(self, client):
        token = _register_and_login(client, prefix="gql-gen-invalid")
        response = _gql(
            client,
            _GENERATE_MUTATION,
            token,
            variables={"periodType": "yearly", "anchorDate": None},
        )
        body = response.get_json()
        assert body.get("errors")
        assert any("period_type" in e.get("message", "") for e in body["errors"])

    def test_rejects_invalid_anchor_date(self, client):
        token = _register_and_login(client, prefix="gql-gen-bad-date")
        response = _gql(
            client,
            _GENERATE_MUTATION,
            token,
            variables={"periodType": "daily", "anchorDate": "17/05/2026"},
        )
        body = response.get_json()
        assert body.get("errors")
        assert any("anchor_date" in e.get("message", "") for e in body["errors"])

    def test_requires_auth(self, client):
        response = _gql(client, _GENERATE_MUTATION, variables={"periodType": "daily"})
        body = response.get_json()
        assert response.status_code == 401 or body.get("errors")

    def test_returns_items_with_dimension_when_provider_returns_payload(
        self, app, client
    ):
        token = _register_and_login(client, prefix="gql-gen-ok")
        # Grant entitlement so the service does not block on Premium gate.
        from flask_jwt_extended import decode_token

        from app.services.entitlement_service import grant_entitlement

        with app.app_context():
            user_id = UUID(decode_token(token)["sub"])
            grant_entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source="trial",
            )
            from app.extensions.database import db

            db.session.commit()

        fake_result = {
            "id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "period_type": "daily",
            "period_label": "2026-05-18",
            "period_start": "2026-05-18",
            "period_end": "2026-05-18",
            "summary": "Resumo do dia.",
            "items": [
                {
                    "type": "saude_financeira",
                    "dimension": "credit_cards",
                    "title": "Cartão Nubank no limite",
                    "message": "Você usou 80% do limite.",
                    "evidence": ["credit_cards[0].utilization_pct"],
                }
            ],
            "context_version": "financial_insight_snapshot.v1",
            "context_hash": "abc",
            "cached": False,
            "model": "gpt-4o-mini",
            "tokens_used": 50,
            "cost_usd": 0.0001,
        }
        with patch("app.graphql.mutations.ai_insight.AIAdvisoryService") as MockSvc:
            instance = MockSvc.return_value
            instance.generate_financial_insights.return_value = fake_result
            response = _gql(
                client,
                _GENERATE_MUTATION,
                token,
                variables={"periodType": "daily", "anchorDate": "2026-05-18"},
            )
        body = response.get_json()
        assert "errors" not in body or not body["errors"], body
        data = body["data"]["generateAiInsight"]
        assert data["ok"] is True
        assert data["id"] == "cccccccc-cccc-cccc-cccc-cccccccccccc"
        assert data["summary"] == "Resumo do dia."
        assert len(data["items"]) == 1
        assert data["items"][0]["dimension"] == "credit_cards"
        assert data["items"][0]["evidence"] == ["credit_cards[0].utilization_pct"]

    def test_exposes_forecast_flag_for_future_period(self, app, client):
        """GraphQL parity (#1393): a future-month generation returns forecast=true.

        Mirrors the REST `forecast` field on POST /ai/insights/generate.
        """
        token = _register_and_login(client, prefix="gql-gen-forecast")
        from flask_jwt_extended import decode_token

        from app.services.entitlement_service import grant_entitlement

        with app.app_context():
            user_id = UUID(decode_token(token)["sub"])
            grant_entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source="trial",
            )
            from app.extensions.database import db

            db.session.commit()

        fake_result = {
            "period_type": "monthly",
            "period_label": "2026-12",
            "period_start": "2026-12-01",
            "period_end": "2026-12-31",
            "summary": "Previsão de dezembro.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "gpt-4o-mini",
            "tokens_used": 50,
            "cost_usd": 0.0001,
            "forecast": True,
        }
        with patch("app.graphql.mutations.ai_insight.AIAdvisoryService") as MockSvc:
            instance = MockSvc.return_value
            instance.generate_financial_insights.return_value = fake_result
            response = _gql(
                client,
                _GENERATE_MUTATION,
                token,
                variables={"periodType": "monthly", "anchorDate": "2026-12-01"},
            )

        body = response.get_json()
        assert "errors" not in body or not body["errors"], body
        assert body["data"]["generateAiInsight"]["forecast"] is True

    def test_forecast_defaults_false_when_absent(self, app, client):
        """A present-period result without an explicit forecast reads as false."""
        token = _register_and_login(client, prefix="gql-gen-noforecast")
        from flask_jwt_extended import decode_token

        from app.services.entitlement_service import grant_entitlement

        with app.app_context():
            user_id = UUID(decode_token(token)["sub"])
            grant_entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source="trial",
            )
            from app.extensions.database import db

            db.session.commit()

        fake_result = {
            "period_type": "daily",
            "period_label": "2026-05-18",
            "period_start": "2026-05-18",
            "period_end": "2026-05-18",
            "summary": "Resumo do dia.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "gpt-4o-mini",
            "tokens_used": 50,
            "cost_usd": 0.0001,
        }
        with patch("app.graphql.mutations.ai_insight.AIAdvisoryService") as MockSvc:
            instance = MockSvc.return_value
            instance.generate_financial_insights.return_value = fake_result
            response = _gql(
                client,
                _GENERATE_MUTATION,
                token,
                variables={"periodType": "daily", "anchorDate": "2026-05-18"},
            )

        body = response.get_json()
        assert "errors" not in body or not body["errors"], body
        assert body["data"]["generateAiInsight"]["forecast"] is False

    def test_passes_timezone_header_to_generation_service(self, app, client):
        token = _register_and_login(client, prefix="gql-gen-tz")
        from flask_jwt_extended import decode_token

        from app.services.entitlement_service import grant_entitlement

        with app.app_context():
            user_id = UUID(decode_token(token)["sub"])
            grant_entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source="trial",
            )
            from app.extensions.database import db

            db.session.commit()

        fake_result = {
            "period_type": "daily",
            "period_label": "2026-05-22",
            "period_start": "2026-05-22",
            "period_end": "2026-05-22",
            "summary": "Resumo com timezone.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "gpt-4o-mini",
            "tokens_used": 50,
            "cost_usd": 0.0001,
        }
        with patch("app.graphql.mutations.ai_insight.AIAdvisoryService") as MockSvc:
            instance = MockSvc.return_value
            instance.generate_financial_insights.return_value = fake_result
            response = _gql(
                client,
                _GENERATE_MUTATION,
                token,
                variables={"periodType": "daily", "anchorDate": None},
                extra_headers={"X-Auraxis-Timezone": "Pacific/Kiritimati"},
            )

        body = response.get_json()
        assert "errors" not in body or not body["errors"], body
        instance.generate_financial_insights.assert_called_once_with(
            period_type="daily",
            anchor_date=None,
            timezone_name="Pacific/Kiritimati",
            timezone_fallback=False,
        )


_FLUIDA_MUTATION = """
mutation Gen($periodType: String!, $anchorDate: String) {
  generateAiInsight(periodType: $periodType, anchorDate: $anchorDate) {
    ok
    summary
    paragraphs
    retro { key label value caption sign }
    series { daily weekly }
    highlights { label value sub }
  }
}
"""


class TestGenerateAiInsightFluidaFields:
    def test_exposes_structured_fluida_fields(self, app, client):
        token = _register_and_login(client, prefix="gql-gen-fluida")
        from flask_jwt_extended import decode_token

        from app.services.entitlement_service import grant_entitlement

        with app.app_context():
            user_id = UUID(decode_token(token)["sub"])
            grant_entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source="trial",
            )
            from app.extensions.database import db

            db.session.commit()

        fake_result = {
            "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "period_type": "daily",
            "period_label": "2026-06-15",
            "period_start": "2026-06-15",
            "period_end": "2026-06-15",
            "summary": "Resumo do dia.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "context_hash": "abc",
            "cached": False,
            "model": "gpt-4o-mini",
            "tokens_used": 50,
            "cost_usd": 0.0001,
            "forecast": False,
            "paragraphs": ["Resumo do dia."],
            "retro": [
                {
                    "key": "yesterday",
                    "label": "Ontem",
                    "value": 42.0,
                    "caption": "Saídas de ontem",
                    "sign": "neg",
                }
            ],
            "series": {"daily": [0.0] * 7, "weekly": [0.0] * 6},
            "highlights": [
                {"label": "Maior gasto do mês", "value": 1800.0, "sub": "Aluguel"}
            ],
        }
        with patch("app.graphql.mutations.ai_insight.AIAdvisoryService") as MockSvc:
            instance = MockSvc.return_value
            instance.generate_financial_insights.return_value = fake_result
            response = _gql(
                client,
                _FLUIDA_MUTATION,
                token,
                variables={"periodType": "daily", "anchorDate": "2026-06-15"},
            )

        body = response.get_json()
        assert "errors" not in body or not body["errors"], body
        data = body["data"]["generateAiInsight"]
        assert data["paragraphs"] == ["Resumo do dia."]
        assert data["retro"][0]["key"] == "yesterday"
        assert data["retro"][0]["value"] == 42.0
        assert data["retro"][0]["sign"] == "neg"
        assert data["series"]["daily"] == [0.0] * 7
        assert data["series"]["weekly"] == [0.0] * 6
        assert data["highlights"][0]["label"] == "Maior gasto do mês"
        assert data["highlights"][0]["value"] == 1800.0
        assert data["highlights"][0]["sub"] == "Aluguel"


_LEAD_MUTATION = """
mutation Gen($periodType: String!, $anchorDate: String) {
  generateAiInsight(periodType: $periodType, anchorDate: $anchorDate) {
    ok
    lead { severity readMin title lead nextStep }
  }
}
"""


class TestGenerateAiInsightLead:
    def test_exposes_editorial_lead(self, app, client):
        token = _register_and_login(client, prefix="gql-gen-lead")
        from flask_jwt_extended import decode_token

        from app.services.entitlement_service import grant_entitlement

        with app.app_context():
            user_id = UUID(decode_token(token)["sub"])
            grant_entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source="trial",
            )
            from app.extensions.database import db

            db.session.commit()

        fake_result = {
            "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "period_type": "daily",
            "period_label": "2026-06-15",
            "period_start": "2026-06-15",
            "period_end": "2026-06-15",
            "summary": "Dia leve. Continue acompanhando.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "gpt-4o-mini",
            "tokens_used": 50,
            "cost_usd": 0.0001,
            "forecast": False,
            "paragraphs": ["Dia leve.", "Continue acompanhando."],
            "retro": [],
            "series": {"daily": [0.0] * 7, "weekly": [0.0] * 6},
            "highlights": [],
            "lead": {
                "severity": "ok",
                "read_min": 15,
                "title": "Dia leve.",
                "lead": "Dia leve. Continue acompanhando.",
                "next_step": "Continue acompanhando.",
            },
        }
        with patch("app.graphql.mutations.ai_insight.AIAdvisoryService") as MockSvc:
            instance = MockSvc.return_value
            instance.generate_financial_insights.return_value = fake_result
            response = _gql(
                client,
                _LEAD_MUTATION,
                token,
                variables={"periodType": "daily", "anchorDate": "2026-06-15"},
            )

        body = response.get_json()
        assert "errors" not in body or not body["errors"], body
        lead = body["data"]["generateAiInsight"]["lead"]
        assert lead["severity"] == "ok"
        assert lead["readMin"] == 15
        assert lead["title"] == "Dia leve."
        assert lead["lead"] == "Dia leve. Continue acompanhando."
        assert lead["nextStep"] == "Continue acompanhando."

    def test_lead_is_null_when_absent_from_result(self, app, client):
        """A result without a lead key resolves to null (defensive)."""
        token = _register_and_login(client, prefix="gql-gen-nolead")
        from flask_jwt_extended import decode_token

        from app.services.entitlement_service import grant_entitlement

        with app.app_context():
            user_id = UUID(decode_token(token)["sub"])
            grant_entitlement(
                user_id=user_id,
                feature_key="advanced_simulations",
                source="trial",
            )
            from app.extensions.database import db

            db.session.commit()

        fake_result = {
            "period_type": "daily",
            "period_label": "2026-06-15",
            "period_start": "2026-06-15",
            "period_end": "2026-06-15",
            "summary": "Sem lead.",
            "items": [],
            "context_version": "financial_insight_snapshot.v1",
            "cached": False,
            "model": "gpt-4o-mini",
            "tokens_used": 50,
            "cost_usd": 0.0001,
        }
        with patch("app.graphql.mutations.ai_insight.AIAdvisoryService") as MockSvc:
            instance = MockSvc.return_value
            instance.generate_financial_insights.return_value = fake_result
            response = _gql(
                client,
                _LEAD_MUTATION,
                token,
                variables={"periodType": "daily", "anchorDate": "2026-06-15"},
            )

        body = response.get_json()
        assert "errors" not in body or not body["errors"], body
        assert body["data"]["generateAiInsight"]["lead"] is None
