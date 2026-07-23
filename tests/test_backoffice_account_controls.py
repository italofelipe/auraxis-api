from __future__ import annotations

import uuid
from datetime import timedelta

from flask_jwt_extended import create_access_token, create_refresh_token, get_jti
from werkzeug.security import generate_password_hash

from app.config.plan_features import PREMIUM_FEATURES
from app.extensions.database import db
from app.models.premium_override import PremiumOverride
from app.models.refresh_token import RefreshToken
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services.account_control_service import block_user, unblock_user
from app.services.entitlement_service import has_entitlement
from app.services.premium_override_service import (
    grant_premium_override,
    revoke_premium_override,
)
from app.utils.datetime_utils import utc_now_naive


def _user(app, *, email: str = "backoffice-user@auraxis.test") -> tuple[uuid.UUID, str]:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Backoffice User",
            email=email,
            password=generate_password_hash("ValidPassword1!"),
        )
        db.session.add(user)
        db.session.commit()
        return user.id, user.email


def test_block_revokes_all_sessions_and_denies_existing_access(app, client) -> None:
    user_id, _ = _user(app)
    with app.app_context():
        access = create_access_token(str(user_id))
        refresh = create_refresh_token(str(user_id))
        stored = db.session.get(User, user_id)
        assert stored is not None
        stored.current_jti = get_jti(access)
        stored.refresh_token_jti = get_jti(refresh)
        db.session.add(
            RefreshToken(
                user_id=user_id,
                token_hash="a" * 64,
                jti=get_jti(refresh),
                current_access_jti=get_jti(access),
                family_id=uuid.uuid4(),
                expires_at=utc_now_naive() + timedelta(days=1),
            )
        )
        block_user(user_id=user_id, reason="Fraud review", blocked_by="admin@test")
        db.session.commit()

    response = client.get(
        "/user/me",
        headers={
            "Authorization": f"Bearer {access}",
            "X-API-Contract": "v2",
        },
    )
    assert response.status_code == 403, response.get_json()
    assert response.get_json()["error"]["code"] == "ACCOUNT_BLOCKED"
    with app.app_context():
        stored = db.session.get(User, user_id)
        session = RefreshToken.query.filter_by(user_id=user_id).one()
        assert stored is not None and stored.current_jti is None
        assert session.revoked_at is not None


def test_blocked_user_cannot_login_and_unblock_requires_new_login(app, client) -> None:
    user_id, email = _user(app, email="blocked-login@auraxis.test")
    with app.app_context():
        block_user(user_id=user_id, reason="Support hold", blocked_by="admin@test")
        db.session.commit()

    blocked = client.post(
        "/auth/login",
        json={"email": email, "password": "ValidPassword1!"},
        headers={"X-API-Contract": "v2"},
    )
    assert blocked.status_code == 403
    assert blocked.get_json()["error"]["code"] == "ACCOUNT_BLOCKED"

    with app.app_context():
        unblock_user(user_id=user_id)
        db.session.commit()
    allowed = client.post(
        "/auth/login",
        json={"email": email, "password": "ValidPassword1!"},
    )
    assert allowed.status_code == 200
    with app.app_context():
        stored = db.session.get(User, user_id)
        assert stored is not None and stored.last_login_at is not None


def test_premium_override_does_not_mutate_subscription(app) -> None:
    user_id, _ = _user(app, email="manual-premium@auraxis.test")
    with app.app_context():
        subscription = Subscription(
            user_id=user_id,
            plan_code="free",
            status=SubscriptionStatus.FREE,
        )
        db.session.add(subscription)
        grant_premium_override(
            user_id=user_id,
            reason="Customer success courtesy",
            granted_by="admin@test",
        )
        db.session.commit()
        assert all(has_entitlement(user_id, feature) for feature in PREMIUM_FEATURES)
        stored_subscription = Subscription.query.filter_by(user_id=user_id).one()
        assert stored_subscription.plan_code == "free"
        assert stored_subscription.status == SubscriptionStatus.FREE

        revoke_premium_override(
            user_id=user_id,
            reason="Courtesy period ended",
            revoked_by="admin@test",
        )
        db.session.commit()
        assert not any(
            has_entitlement(user_id, feature) for feature in PREMIUM_FEATURES
        )
        override = PremiumOverride.query.filter_by(user_id=user_id).one()
        assert override.revoked_at is not None


def test_expired_premium_override_is_inactive(app) -> None:
    user_id, _ = _user(app, email="expired-premium@auraxis.test")
    with app.app_context():
        override = PremiumOverride(
            user_id=user_id,
            granted_at=utc_now_naive() - timedelta(days=2),
            expires_at=utc_now_naive() - timedelta(days=1),
            reason="Expired test",
            granted_by="admin@test",
        )
        db.session.add(override)
        db.session.commit()
        assert has_entitlement(user_id, next(iter(PREMIUM_FEATURES))) is False


def test_migrate_env_cli_creates_auditable_override_without_changing_plan(app) -> None:
    user_id, _ = _user(app, email="legacy-premium@auraxis.test")
    with app.app_context():
        db.session.add(
            Subscription(
                user_id=user_id,
                plan_code="free",
                status=SubscriptionStatus.FREE,
            )
        )
        db.session.commit()
    app.config["AURAXIS_PREMIUM_OVERRIDE_USER_IDS"] = str(user_id)

    result = app.test_cli_runner().invoke(args=["premium-overrides", "migrate-env"])

    assert result.exit_code == 0, result.output
    assert "migrated=1" in result.output
    with app.app_context():
        override = PremiumOverride.query.filter_by(user_id=user_id).one()
        subscription = Subscription.query.filter_by(user_id=user_id).one()
        assert override.granted_by == "system:legacy-premium-override-env"
        assert subscription.plan_code == "free"
        assert subscription.status == SubscriptionStatus.FREE


def test_migrate_env_cli_fails_when_configured_user_is_missing(app) -> None:
    app.config["AURAXIS_PREMIUM_OVERRIDE_USER_IDS"] = str(uuid.uuid4())

    result = app.test_cli_runner().invoke(args=["premium-overrides", "migrate-env"])

    assert result.exit_code != 0
    assert "one or more configured users do not exist" in result.output
