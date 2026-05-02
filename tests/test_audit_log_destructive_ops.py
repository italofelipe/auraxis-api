"""Audit-log coverage for destructive operations across REST + GraphQL.

The GraphQL audit (2026-05-02) flagged that delete-shaped mutations had no
audit trail. The infrastructure (``audit_events`` table +
``record_entity_delete``) already exists from #1052; this PR wires the
remaining domains (goal, wallet, subscription) and pins the contract with
regression tests covering both transports.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest

from app.extensions.database import db
from app.models.audit_event import AuditEvent
from app.models.user import User


@pytest.fixture(autouse=True)
def _enable_audit_persistence():
    """Audit persistence defaults to off in tests; force-enable it for the
    full lifecycle of these specs so the wiring is exercised end-to-end."""

    with patch(
        "app.extensions.audit_trail._is_audit_persistence_enabled",
        return_value=True,
    ):
        yield


def _graphql(
    client: Any,
    query: str,
    variables: dict[str, Any] | None = None,
    token: str | None = None,
) -> Any:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )


def _register_and_login(client: Any, prefix: str) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"
    register = _graphql(
        client,
        """
        mutation Register($name: String!, $email: String!, $password: String!) {
          registerUser(name: $name, email: $email, password: $password) { message }
        }
        """,
        {"name": f"{prefix}-{suffix}", "email": email, "password": password},
    )
    assert register.status_code == 200
    assert "errors" not in register.get_json()

    login = _graphql(
        client,
        """
        mutation Login($email: String!, $password: String!) {
          login(email: $email, password: $password) { token }
        }
        """,
        {"email": email, "password": password},
    )
    body = login.get_json()
    return str(body["data"]["login"]["token"]), email


def _audit_events_for(user_id: UUID, entity_type: str) -> list[AuditEvent]:
    rows = (
        AuditEvent.query.filter_by(
            actor_id=str(user_id),
            entity_type=entity_type,
            action="soft_delete",
        )
        .order_by(AuditEvent.created_at.desc())
        .all()
    )
    return list(rows)


def _user_id_by_email(app: Any, email: str) -> UUID:
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None
        return UUID(str(user.id))


def test_graphql_delete_goal_records_audit_event(client: Any, app: Any) -> None:
    token, email = _register_and_login(client, "audit-goal")
    user_id = _user_id_by_email(app, email)

    create = _graphql(
        client,
        """
        mutation { createGoal(title: "Audit", targetAmount: "1000.00") {
            goal { id }
        } }
        """,
        token=token,
    )
    body = create.get_json()
    assert "errors" not in body, body
    goal_id = body["data"]["createGoal"]["goal"]["id"]

    delete = _graphql(
        client,
        """
        mutation D($goalId: UUID!) { deleteGoal(goalId: $goalId) { ok } }
        """,
        {"goalId": goal_id},
        token=token,
    )
    assert "errors" not in delete.get_json(), delete.get_json()

    with app.app_context():
        events = _audit_events_for(user_id, "goal")
        assert len(events) == 1
        assert events[0].entity_id == goal_id


def test_graphql_delete_wallet_entry_records_audit_event(client: Any, app: Any) -> None:
    token, email = _register_and_login(client, "audit-wallet")
    user_id = _user_id_by_email(app, email)

    create = _graphql(
        client,
        """
        mutation { addWalletEntry(
            name: "Custom",
            value: 100,
            assetClass: "custom",
            registerDate: "2026-01-01",
            shouldBeOnWallet: true
        ) { item { id } } }
        """,
        token=token,
    )
    body = create.get_json()
    assert "errors" not in body, body
    investment_id = body["data"]["addWalletEntry"]["item"]["id"]

    delete = _graphql(
        client,
        """
        mutation D($investmentId: UUID!) {
          deleteWalletEntry(investmentId: $investmentId) { ok }
        }
        """,
        {"investmentId": investment_id},
        token=token,
    )
    assert "errors" not in delete.get_json(), delete.get_json()

    with app.app_context():
        events = _audit_events_for(user_id, "wallet")
        assert len(events) == 1
        assert events[0].entity_id == investment_id


def test_rest_delete_goal_records_audit_event(client: Any, app: Any) -> None:
    """The audit must fire from the REST controller too — the service layer
    is the canonical recording site so both transports stay aligned."""

    suffix = uuid.uuid4().hex[:8]
    email = f"audit-goal-rest-{suffix}@email.com"
    password = "StrongPass@123"
    register = client.post(
        "/auth/register",
        json={
            "name": f"audit-goal-rest-{suffix}",
            "email": email,
            "password": password,
        },
    )
    assert register.status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    token = login.get_json()["token"]
    user_id = _user_id_by_email(app, email)

    create = client.post(
        "/goals",
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
        json={"title": "REST audit", "target_amount": "1000.00"},
    )
    assert create.status_code == 201, create.get_json()
    goal_id = create.get_json()["data"]["goal"]["id"]

    delete = client.delete(
        f"/goals/{goal_id}",
        headers={"Authorization": f"Bearer {token}", "X-API-Contract": "v2"},
    )
    assert delete.status_code in {200, 204}, delete.get_json()

    with app.app_context():
        events = _audit_events_for(user_id, "goal")
        assert len(events) == 1
        assert events[0].entity_id == goal_id


def test_audit_event_not_recorded_when_unauthenticated(client: Any, app: Any) -> None:
    """Auth-failure paths must not leak audit rows — the audit row is the
    success witness, not an attempt log."""

    delete = _graphql(
        client,
        """
        mutation D($goalId: UUID!) { deleteGoal(goalId: $goalId) { ok } }
        """,
        {"goalId": str(uuid.uuid4())},
    )
    body = delete.get_json()
    assert "errors" in body
    with app.app_context():
        # No goal_id matched, no actor — the event count for any actor for
        # entity_type="goal" should remain zero.
        rows = (
            db.session.query(AuditEvent)
            .filter_by(entity_type="goal", action="soft_delete")
            .all()
        )
        assert rows == []
