"""Tests for server-side onboarding completion (#1471).

Covers:
- POST /user/onboarding/complete stamps the marker and is idempotent.
- GET /user/me (v3) exposes product_context.onboarding_completed_at.
- GraphQL completeOnboarding mutation + me.onboardingCompletedAt parity.
- New users start with a null marker (so the wizard shows once).
"""

from __future__ import annotations

from uuid import uuid4

from app.extensions.database import db
from app.models.user import User


def _register_and_login(client, *, prefix: str = "onb") -> str:
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


def _auth(token: str, contract: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if contract:
        headers["X-API-Contract"] = contract
    return headers


def _gql(client, query, token):
    headers = {
        "Authorization": f"Bearer {token}",
        "X-API-Contract": "v2",
        "Content-Type": "application/json",
    }
    return client.post("/graphql", json={"query": query}, headers=headers)


class TestOnboardingCompleteEndpoint:
    def test_new_user_starts_without_onboarding_marker(self, client) -> None:
        token = _register_and_login(client)
        resp = client.get("/user/me", headers=_auth(token, "v3"))
        assert resp.status_code == 200
        product_context = resp.get_json()["data"]["user"]["product_context"]
        assert "onboarding_completed_at" in product_context
        assert product_context["onboarding_completed_at"] is None

    def test_complete_stamps_marker(self, client) -> None:
        token = _register_and_login(client)
        resp = client.post("/user/onboarding/complete", headers=_auth(token, "v2"))
        assert resp.status_code == 200
        completed_at = resp.get_json()["data"]["onboarding_completed_at"]
        assert completed_at is not None

        me = client.get("/user/me", headers=_auth(token, "v3"))
        assert (
            me.get_json()["data"]["user"]["product_context"]["onboarding_completed_at"]
            == completed_at
        )

    def test_complete_is_idempotent(self, client) -> None:
        token = _register_and_login(client)
        first = client.post("/user/onboarding/complete", headers=_auth(token, "v2"))
        second = client.post("/user/onboarding/complete", headers=_auth(token, "v2"))
        assert first.status_code == second.status_code == 200
        # The timestamp must not move on the second call.
        assert (
            first.get_json()["data"]["onboarding_completed_at"]
            == second.get_json()["data"]["onboarding_completed_at"]
        )

    def test_requires_auth(self, client) -> None:
        resp = client.post("/user/onboarding/complete")
        assert resp.status_code == 401


class TestOnboardingGraphQLParity:
    def test_complete_onboarding_mutation_and_me_field(self, client) -> None:
        token = _register_and_login(client)

        mutation = """
        mutation {
          completeOnboarding {
            ok
            onboardingCompletedAt
          }
        }
        """
        resp = _gql(client, mutation, token)
        assert resp.status_code == 200
        data = resp.get_json()["data"]["completeOnboarding"]
        assert data["ok"] is True
        assert data["onboardingCompletedAt"] is not None

        me_query = "query { me { onboardingCompletedAt } }"
        me_resp = _gql(client, me_query, token)
        assert me_resp.status_code == 200
        assert (
            me_resp.get_json()["data"]["me"]["onboardingCompletedAt"]
            == data["onboardingCompletedAt"]
        )

    def test_complete_onboarding_requires_auth(self, client) -> None:
        mutation = "mutation { completeOnboarding { ok } }"
        resp = client.post(
            "/graphql",
            json={"query": mutation},
            headers={"X-API-Contract": "v2", "Content-Type": "application/json"},
        )
        body = resp.get_json()
        assert body.get("errors")


def test_build_profile_reads_onboarding_marker(app) -> None:
    from app.application.services.authenticated_user_context_service import (
        AuthenticatedUserContextService,
    )
    from app.utils.datetime_utils import utc_now_naive

    with app.app_context():
        user = User(name="Onb", email=f"onb-{uuid4().hex[:8]}@e.com", password="x")
        user.onboarding_completed_at = utc_now_naive()
        db.session.add(user)
        db.session.commit()

        profile = AuthenticatedUserContextService.with_defaults().build_profile(user)
        assert (
            profile.onboarding_completed_at == user.onboarding_completed_at.isoformat()
        )
