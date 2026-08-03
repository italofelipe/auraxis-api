"""Period filters + REST↔GraphQL parity for the AI insight history (#1653).

`GET /ai/insights/history` and the `aiInsightHistory` query used to carry two
copies of the same query. Both now read through
``app.services.ai_insight_history_service``, so these tests assert:

- the new optional filters (`period_type`, `period_label`) on both protocols;
- an invalid `period_type` fails loudly (400 / GraphQL error) instead of
  silently returning everything;
- pagination clamping is identical on both protocols;
- both protocols return the same rows for the same filters (parity).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from app.extensions.database import db
from app.models.ai_insight import AIInsight, InsightType

_GQL_HISTORY = """
query AiInsightHistory(
  $page: Int
  $perPage: Int
  $periodType: String
  $periodLabel: String
) {
  aiInsightHistory(
    page: $page
    perPage: $perPage
    periodType: $periodType
    periodLabel: $periodLabel
  ) {
    items {
      id
      periodLabel
      insightType
    }
    page
    perPage
    total
  }
}
"""


def _register_and_login(client, prefix: str = "hist-filter") -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@test.com"
    reg = client.post(
        "/auth/register",
        json={
            "name": f"{prefix}-{suffix}",
            "email": email,
            "password": "StrongPass@123",
        },
    )
    assert reg.status_code == 201
    login = client.post(
        "/auth/login", json={"email": email, "password": "StrongPass@123"}
    )
    assert login.status_code == 200
    return login.get_json()["token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


def _graphql(
    client,
    variables: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/graphql",
        json={"query": _GQL_HISTORY, "variables": variables or {}},
        headers=headers,
    )


def _user_id(app, token: str) -> uuid.UUID:
    with app.app_context():
        from flask_jwt_extended import decode_token

        return uuid.UUID(decode_token(token)["sub"])


def _seed(
    app,
    user_id: uuid.UUID,
    *,
    insight_type: InsightType,
    period_label: str,
    created_at: datetime,
) -> None:
    with app.app_context():
        db.session.add(
            AIInsight(
                user_id=user_id,
                content=f"conteudo {period_label}",
                insight_type=insight_type,
                period_label=period_label,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 31),
                model="gpt-4o-mini",
                tokens_used=100,
                cost_usd=0.00001,
            )
        )
        db.session.commit()
        row = (
            db.session.query(AIInsight)
            .filter_by(user_id=user_id, period_label=period_label)
            .one()
        )
        row.created_at = created_at
        db.session.commit()


def _seed_month_mix(app, token: str) -> uuid.UUID:
    user_id = _user_id(app, token)
    _seed(
        app,
        user_id,
        insight_type=InsightType.monthly,
        period_label="2026-07",
        created_at=datetime(2026, 8, 1, 3, 0, 0, tzinfo=timezone.utc).replace(
            tzinfo=None
        ),
    )
    _seed(
        app,
        user_id,
        insight_type=InsightType.monthly,
        period_label="2026-06",
        created_at=datetime(2026, 7, 1, 3, 0, 0, tzinfo=timezone.utc).replace(
            tzinfo=None
        ),
    )
    _seed(
        app,
        user_id,
        insight_type=InsightType.daily,
        period_label="2026-07-15",
        created_at=datetime(2026, 7, 15, 3, 0, 0, tzinfo=timezone.utc).replace(
            tzinfo=None
        ),
    )
    return user_id


def _rest_items(response) -> list[dict[str, Any]]:
    payload = response.get_json()
    return (payload.get("data") or {}).get("items") or []


class TestRestHistoryFilters:
    def test_filters_by_period_type_and_label(self, app, client) -> None:
        token = _register_and_login(client)
        _seed_month_mix(app, token)

        response = client.get(
            "/ai/insights/history?period_type=monthly&period_label=2026-07",
            headers=_auth(token),
        )

        assert response.status_code == 200
        items = _rest_items(response)
        assert len(items) == 1
        assert items[0]["period_label"] == "2026-07"
        assert items[0]["period_type"] == "monthly"
        assert (response.get_json()["data"])["total"] == 1

    def test_filters_by_period_type_only(self, app, client) -> None:
        token = _register_and_login(client)
        _seed_month_mix(app, token)

        response = client.get(
            "/ai/insights/history?period_type=monthly",
            headers=_auth(token),
        )

        assert response.status_code == 200
        items = _rest_items(response)
        assert [item["period_label"] for item in items] == ["2026-07", "2026-06"]

    def test_no_filter_keeps_returning_everything(self, app, client) -> None:
        token = _register_and_login(client)
        _seed_month_mix(app, token)

        response = client.get("/ai/insights/history", headers=_auth(token))

        assert response.status_code == 200
        assert len(_rest_items(response)) == 3

    def test_invalid_period_type_returns_400(self, app, client) -> None:
        token = _register_and_login(client)

        response = client.get(
            "/ai/insights/history?period_type=quarterly",
            headers=_auth(token),
        )

        assert response.status_code == 400
        body = response.get_json()
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "period_type" in body["message"]

    def test_unknown_period_label_returns_empty_page(self, app, client) -> None:
        token = _register_and_login(client)
        _seed_month_mix(app, token)

        response = client.get(
            "/ai/insights/history?period_type=monthly&period_label=1999-01",
            headers=_auth(token),
        )

        assert response.status_code == 200
        assert _rest_items(response) == []
        assert response.get_json()["data"]["total"] == 0


class TestGraphqlHistoryFilters:
    def test_filters_by_period_type_and_label(self, app, client) -> None:
        token = _register_and_login(client)
        _seed_month_mix(app, token)

        response = _graphql(
            client,
            variables={"periodType": "monthly", "periodLabel": "2026-07"},
            token=token,
        )

        body = response.get_json()
        assert "errors" not in body
        result = body["data"]["aiInsightHistory"]
        assert result["total"] == 1
        assert result["items"][0]["periodLabel"] == "2026-07"

    def test_invalid_period_type_returns_error(self, app, client) -> None:
        token = _register_and_login(client)

        response = _graphql(client, variables={"periodType": "quarterly"}, token=token)

        body = response.get_json()
        assert body.get("errors")
        assert "period_type" in body["errors"][0]["message"]
        assert body["errors"][0]["extensions"]["code"] == "VALIDATION_ERROR"

    def test_pagination_is_clamped_like_rest(self, app, client) -> None:
        """Page < 1 used to produce a negative OFFSET on GraphQL only."""
        token = _register_and_login(client)
        _seed_month_mix(app, token)

        # Slim selection: the complexity guard rejects a wide query multiplied
        # by a large perPage before the resolver ever runs.
        response = client.post(
            "/graphql",
            json={
                "query": (
                    "query H($page: Int, $perPage: Int) {"
                    "  aiInsightHistory(page: $page, perPage: $perPage) {"
                    "    items { id } page perPage total } }"
                ),
                "variables": {"page": 0, "perPage": 51},
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        body = response.get_json()
        assert "errors" not in body
        result = body["data"]["aiInsightHistory"]
        assert result["page"] == 1
        assert result["perPage"] == 50
        assert result["total"] == 3


class TestServiceNormalizers:
    def test_pagination_falls_back_on_garbage(self) -> None:
        from app.services.ai_insight_history_service import (
            DEFAULT_PAGE,
            DEFAULT_PER_PAGE,
            MAX_PER_PAGE,
            normalize_pagination,
        )

        assert normalize_pagination(None, None) == (DEFAULT_PAGE, DEFAULT_PER_PAGE)
        assert normalize_pagination("abc", "xyz") == (DEFAULT_PAGE, DEFAULT_PER_PAGE)
        assert normalize_pagination("-3", "0") == (1, 1)
        assert normalize_pagination("2", "999") == (2, MAX_PER_PAGE)

    def test_period_type_normalization(self) -> None:
        import pytest

        from app.services.ai_insight_history_service import (
            AIInsightHistoryValidationError,
            normalize_period_label,
            normalize_period_type,
        )

        assert normalize_period_type(None) is None
        assert normalize_period_type("  ") is None
        assert normalize_period_type(" Monthly ") is InsightType.monthly
        assert normalize_period_label("  2026-07 ") == "2026-07"
        assert normalize_period_label("   ") is None
        with pytest.raises(AIInsightHistoryValidationError):
            normalize_period_type("quarterly")


class TestRestGraphqlParity:
    def test_same_rows_for_same_filters(self, app, client) -> None:
        token = _register_and_login(client)
        _seed_month_mix(app, token)

        rest = client.get(
            "/ai/insights/history?period_type=monthly",
            headers=_auth(token),
        )
        gql = _graphql(client, variables={"periodType": "monthly"}, token=token)

        rest_body = rest.get_json()["data"]
        gql_body = gql.get_json()["data"]["aiInsightHistory"]

        assert rest_body["total"] == gql_body["total"]
        assert rest_body["page"] == gql_body["page"]
        assert rest_body["per_page"] == gql_body["perPage"]
        assert [item["id"] for item in rest_body["items"]] == [
            item["id"] for item in gql_body["items"]
        ]
