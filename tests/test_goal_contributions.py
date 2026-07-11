"""Tests for goal contributions — deposits/withdrawals + history (#1470).

Covers REST POST/GET /goals/{id}/contributions and GraphQL parity
(recordGoalContribution mutation + goalContributions query):
- deposits add, withdrawals subtract, below-zero rejected
- zero amount and future date rejected
- reaching target auto-completes the goal
- history is paginated, newest first
- ownership enforced
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from app.extensions.database import db
from app.models.goal_contribution import GoalContribution


def _register_and_login(client, *, prefix: str = "gc") -> str:
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-API-Contract": "v2"}


def _create_goal(client, token, *, target="1000.00", current="0.00") -> str:
    resp = client.post(
        "/goals",
        json={"title": "Reserva", "target_amount": target, "current_amount": current},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.get_json()
    return resp.get_json()["data"]["goal"]["id"]


def _gql(client, query, token, variables=None):
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers={**_auth(token), "Content-Type": "application/json"},
    )


class TestRecordContributionRest:
    def test_deposit_adds_to_current_amount(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token, target="1000.00", current="100.00")

        resp = client.post(
            f"/goals/{goal_id}/contributions",
            json={"amount": "250.00", "note": "salário"},
            headers=_auth(token),
        )
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["goal"]["current_amount"] == "350.00"
        assert data["contribution"]["amount"] == "250.00"
        assert data["contribution"]["note"] == "salário"
        # Default occurred_at is the UTC date (utc_now_naive) — after ~21:00 BRT
        # it is already "tomorrow" locally, so accept either date.
        assert data["contribution"]["occurred_at"] in {
            date.today().isoformat(),
            datetime.now(timezone.utc).date().isoformat(),
        }

    def test_withdrawal_subtracts(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token, current="500.00")

        resp = client.post(
            f"/goals/{goal_id}/contributions",
            json={"amount": "-200.00"},
            headers=_auth(token),
        )
        assert resp.status_code == 201
        assert resp.get_json()["data"]["goal"]["current_amount"] == "300.00"

    def test_withdrawal_below_zero_is_rejected(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token, current="100.00")

        resp = client.post(
            f"/goals/{goal_id}/contributions",
            json={"amount": "-150.00"},
            headers=_auth(token),
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "INSUFFICIENT_BALANCE"

    def test_zero_amount_is_rejected(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token)
        resp = client.post(
            f"/goals/{goal_id}/contributions",
            json={"amount": "0"},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_future_date_is_rejected(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token)
        future = (date.today() + timedelta(days=2)).isoformat()
        resp = client.post(
            f"/goals/{goal_id}/contributions",
            json={"amount": "10.00", "occurred_at": future},
            headers=_auth(token),
        )
        assert resp.status_code == 400

    def test_reaching_target_completes_goal(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token, target="1000.00", current="900.00")

        resp = client.post(
            f"/goals/{goal_id}/contributions",
            json={"amount": "100.00"},
            headers=_auth(token),
        )
        assert resp.status_code == 201
        assert resp.get_json()["data"]["goal"]["status"] == "completed"

    def test_backdated_contribution_is_accepted(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token)
        past = (date.today() - timedelta(days=10)).isoformat()
        resp = client.post(
            f"/goals/{goal_id}/contributions",
            json={"amount": "50.00", "occurred_at": past},
            headers=_auth(token),
        )
        assert resp.status_code == 201
        assert resp.get_json()["data"]["contribution"]["occurred_at"] == past


class TestListContributionsRest:
    def test_history_is_paginated_newest_first(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token, current="0.00")
        for i in range(3):
            day = (date.today() - timedelta(days=i)).isoformat()
            client.post(
                f"/goals/{goal_id}/contributions",
                json={"amount": "10.00", "occurred_at": day, "note": f"n{i}"},
                headers=_auth(token),
            )

        resp = client.get(
            f"/goals/{goal_id}/contributions?page=1&per_page=2", headers=_auth(token)
        )
        assert resp.status_code == 200
        body = resp.get_json()
        items = body["data"]["items"]
        assert len(items) == 2
        # newest first → today's entry (n0) leads.
        assert items[0]["occurred_at"] in {
            date.today().isoformat(),
            datetime.now(timezone.utc).date().isoformat(),
        }
        assert body["meta"]["pagination"]["total"] == 3

    def test_other_user_cannot_list(self, client) -> None:
        owner = _register_and_login(client, prefix="gc-owner")
        goal_id = _create_goal(client, owner)
        stranger = _register_and_login(client, prefix="gc-stranger")
        resp = client.get(f"/goals/{goal_id}/contributions", headers=_auth(stranger))
        assert resp.status_code == 403


class TestContributionGraphQLParity:
    def test_record_and_list_via_graphql(self, client) -> None:
        token = _register_and_login(client)
        goal_id = _create_goal(client, token, target="1000.00", current="0.00")

        mutation = """
        mutation Record($id: UUID!, $amount: String!) {
          recordGoalContribution(goalId: $id, amount: $amount) {
            message
            goal { currentAmount }
            contribution { amount occurredAt }
          }
        }
        """
        resp = _gql(client, mutation, token, {"id": str(goal_id), "amount": "120.00"})
        assert resp.status_code == 200, resp.get_json()
        payload = resp.get_json()["data"]["recordGoalContribution"]
        assert payload["goal"]["currentAmount"] == "120.00"
        assert payload["contribution"]["amount"] == "120.00"

        query = """
        query History($id: UUID!) {
          goalContributions(goalId: $id) {
            items { amount occurredAt }
            pagination { total }
          }
        }
        """
        list_resp = _gql(client, query, token, {"id": str(goal_id)})
        assert list_resp.status_code == 200
        data = list_resp.get_json()["data"]["goalContributions"]
        assert data["pagination"]["total"] == 1
        assert data["items"][0]["amount"] == "120.00"

    def test_record_requires_auth(self, client) -> None:
        mutation = """
        mutation { recordGoalContribution(goalId: "%s", amount: "10") { message } }
        """ % str(uuid4())
        resp = client.post(
            "/graphql",
            json={"query": mutation},
            headers={"X-API-Contract": "v2", "Content-Type": "application/json"},
        )
        assert resp.get_json().get("errors")


def test_contribution_persists_occurred_at(app) -> None:
    with app.app_context():
        contribution = GoalContribution(
            goal_id=uuid4(),
            user_id=uuid4(),
            amount="10.00",
            occurred_at=date(2026, 1, 15),
        )
        db.session.add(contribution)
        db.session.commit()
        stored = db.session.get(GoalContribution, contribution.id)
        assert stored is not None
        assert stored.occurred_at == date(2026, 1, 15)
