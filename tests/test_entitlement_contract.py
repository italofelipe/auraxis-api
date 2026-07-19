"""Integration tests for Entitlement endpoints (J7-1)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Dict

from app.extensions.database import db
from app.models.entitlement import Entitlement, EntitlementSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _auth(token: str, v2: bool = False) -> Dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if v2:
        headers["X-API-Contract"] = "v2"
    return headers


def _grant_entitlement(
    app,
    user_id: str,
    feature_key: str,
    *,
    expires_at: datetime | None = None,
) -> None:
    with app.app_context():
        ent = Entitlement(
            user_id=uuid.UUID(user_id),
            feature_key=feature_key,
            source=EntitlementSource.SUBSCRIPTION,
            expires_at=expires_at,
        )
        db.session.add(ent)
        db.session.commit()


# ---------------------------------------------------------------------------
# GET /entitlements — list
# ---------------------------------------------------------------------------


def test_entitlements_list_new_user_has_free_features(client) -> None:
    """#1569 — signup bootstraps a Free subscription, not a trial.

    Trial entitlements now arrive with the ``subscription.trial_started``
    webhook, once the customer has tokenised a card at checkout.
    """
    from app.config.plan_features import PLAN_FEATURES

    token = _register_and_login(client, prefix="ent-free")
    resp = client.get("/entitlements", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    granted_keys = {e["feature_key"] for e in body["items"]}
    assert granted_keys == set(PLAN_FEATURES["free"])
    assert granted_keys != set(PLAN_FEATURES["trial"])


def test_entitlements_list_requires_auth(client) -> None:
    resp = client.get("/entitlements")
    assert resp.status_code == 401


def test_entitlements_list_with_data(client, app) -> None:
    token = _register_and_login(client, prefix="ent-list")
    # Retrieve the user ID from auth
    me_resp = client.get("/user/profile", headers=_auth(token))
    profile_body = me_resp.get_json()
    # Profile response may use "data" or "user" key depending on contract version
    if "data" in profile_body:
        user_id = profile_body["data"]["id"]
    else:
        user_id = profile_body["user"]["id"]

    _grant_entitlement(app, user_id, "export_pdf")

    resp = client.get("/entitlements", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["items"]) >= 1
    keys = [item["feature_key"] for item in body["items"]]
    assert "export_pdf" in keys


# ---------------------------------------------------------------------------
# GET /entitlements/check — check
# ---------------------------------------------------------------------------


def test_entitlement_check_missing_param(client) -> None:
    token = _register_and_login(client, prefix="ent-check-bad")
    resp = client.get("/entitlements/check", headers=_auth(token))
    assert resp.status_code == 400


def test_entitlement_check_requires_auth(client) -> None:
    resp = client.get("/entitlements/check?feature_key=export_pdf")
    assert resp.status_code == 401


def test_entitlement_check_false_when_absent(client) -> None:
    token = _register_and_login(client, prefix="ent-check-false")
    resp = client.get(
        "/entitlements/check?feature_key=nonexistent_feature",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["feature_key"] == "nonexistent_feature"
    assert body["active"] is False


def test_entitlement_check_true_when_present(client, app) -> None:
    token = _register_and_login(client, prefix="ent-check-true")
    me_resp = client.get("/user/profile", headers=_auth(token))
    profile_body = me_resp.get_json()
    user_id = profile_body.get("data", {}).get("id") or profile_body["user"]["id"]

    _grant_entitlement(app, user_id, "ai_advisor")

    resp = client.get(
        "/entitlements/check?feature_key=ai_advisor",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["active"] is True


def test_entitlement_check_false_when_expired(client, app) -> None:
    token = _register_and_login(client, prefix="ent-check-exp")
    me_resp = client.get("/user/profile", headers=_auth(token))
    profile_body = me_resp.get_json()
    user_id = profile_body.get("data", {}).get("id") or profile_body["user"]["id"]

    past = datetime.utcnow() - timedelta(days=1)
    _grant_entitlement(app, user_id, "expired_feature", expires_at=past)

    resp = client.get(
        "/entitlements/check?feature_key=expired_feature",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["active"] is False


# ---------------------------------------------------------------------------
# V2 contract smoke test
# ---------------------------------------------------------------------------


def test_entitlements_v2_contract(client) -> None:
    token = _register_and_login(client, prefix="ent-v2")
    resp = client.get("/entitlements", headers=_auth(token, v2=True))
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert "items" in body["data"]
