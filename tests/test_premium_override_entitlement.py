from __future__ import annotations

import uuid
from datetime import datetime

from flask_jwt_extended import create_access_token, get_jti

from app.extensions.database import db
from app.models.premium_override import PremiumOverride
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User

_PREMIUM_OVERRIDE_CONFIG_KEY = "AURAXIS_PREMIUM_OVERRIDE_USER_IDS"
_PREMIUM_FEATURE = "advanced_simulations"


def _create_authenticated_user(
    app,
    *,
    user_id: uuid.UUID,
    email: str,
    plan_code: str = "free",
    status: SubscriptionStatus = SubscriptionStatus.FREE,
) -> str:
    with app.app_context():
        user = User(
            id=user_id,
            name="Premium Override Test",
            email=email,
            password="hash",
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(
            Subscription(
                user_id=user.id,
                plan_code=plan_code,
                status=status,
            )
        )
        db.session.flush()

        token = create_access_token(identity=str(user.id))
        user.current_jti = get_jti(token)
        db.session.commit()
        return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_configured_override_preserves_free_plan_and_grants_access(
    app,
    client,
) -> None:
    user_id = uuid.uuid4()
    app.config[_PREMIUM_OVERRIDE_CONFIG_KEY] = str(user_id)
    token = _create_authenticated_user(
        app,
        user_id=user_id,
        email="premium-override@auraxis.test",
    )
    with app.app_context():
        stale_subscription = Subscription.query.filter_by(user_id=user_id).one()
        stale_subscription.trial_ends_at = datetime(2026, 5, 1)
        stale_subscription.current_period_end = datetime(2026, 5, 1)
        stale_subscription.canceled_at = datetime(2026, 5, 1)
        db.session.commit()

    response = client.get("/subscriptions/me", headers=_auth(token))

    assert response.status_code == 200, response.get_json()
    subscription = response.get_json()["data"]["subscription"]
    assert subscription["plan_code"] == "free"
    assert subscription["offer_code"] == "free"
    assert subscription["status"] == "free"
    assert response.get_json()["data"]["effective_access"] == "premium"

    with app.app_context():
        stored = Subscription.query.filter_by(user_id=user_id).one()
        assert stored.plan_code == "free"
        assert stored.status == SubscriptionStatus.FREE
        assert stored.trial_ends_at == datetime(2026, 5, 1)
        assert stored.current_period_end == datetime(2026, 5, 1)
        assert stored.canceled_at == datetime(2026, 5, 1)
        override = PremiumOverride.query.filter_by(user_id=user_id).one()
        assert override.reason == "Migrated from AURAXIS_PREMIUM_OVERRIDE_USER_IDS"
        assert override.granted_by == "system:legacy-premium-override-env"
        assert override.expires_at is None


def test_configured_override_entitlement_check_is_active_without_subscription_call(
    app,
    client,
) -> None:
    user_id = uuid.uuid4()
    app.config[_PREMIUM_OVERRIDE_CONFIG_KEY] = str(user_id)
    token = _create_authenticated_user(
        app,
        user_id=user_id,
        email="premium-override-check@auraxis.test",
    )

    response = client.get(
        f"/entitlements/check?feature_key={_PREMIUM_FEATURE}",
        headers=_auth(token),
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["active"] is True


def test_unconfigured_user_is_not_promoted_by_identity(
    app,
    client,
) -> None:
    user_id = uuid.uuid4()
    app.config[_PREMIUM_OVERRIDE_CONFIG_KEY] = ""
    token = _create_authenticated_user(
        app,
        user_id=user_id,
        email="not-configured@auraxis.test",
    )

    subscription_response = client.get("/subscriptions/me", headers=_auth(token))

    assert subscription_response.status_code == 200, subscription_response.get_json()
    subscription = subscription_response.get_json()["data"]["subscription"]
    assert subscription["plan_code"] == "free"
    assert subscription["offer_code"] == "free"
    assert subscription["status"] == "free"


def test_regular_free_user_is_not_promoted(
    app,
    client,
) -> None:
    user_id = uuid.uuid4()
    app.config[_PREMIUM_OVERRIDE_CONFIG_KEY] = str(uuid.uuid4())
    token = _create_authenticated_user(
        app,
        user_id=user_id,
        email="regular-free@auraxis.test",
    )

    subscription_response = client.get("/subscriptions/me", headers=_auth(token))
    entitlement_response = client.get(
        f"/entitlements/check?feature_key={_PREMIUM_FEATURE}",
        headers=_auth(token),
    )

    assert subscription_response.status_code == 200, subscription_response.get_json()
    subscription = subscription_response.get_json()["data"]["subscription"]
    assert subscription["plan_code"] == "free"
    assert subscription["offer_code"] == "free"
    assert subscription["status"] == "free"
    assert entitlement_response.status_code == 200, entitlement_response.get_json()
    assert entitlement_response.get_json()["active"] is False
