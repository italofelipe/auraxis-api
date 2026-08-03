"""#1599 — dunning grace window before revoking premium on payment_failed.

Covers the three acceptance paths (isolated payment_failed keeps premium,
retry keeps continuity, lapsed grace downgrades + emails) plus the safe legacy
default (a PAST_DUE without a grace date still revokes immediately).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from app.config.plan_features import PREMIUM_FEATURES
from app.extensions.database import db
from app.models.entitlement import Entitlement
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User
from app.services.entitlement_service import sync_entitlements_from_subscription
from app.services.subscription_service import apply_subscription_snapshot
from app.utils.datetime_utils import utc_now_naive

_PREMIUM_FEATURE = next(iter(PREMIUM_FEATURES))


def _make_active_premium_user_and_sub() -> tuple[User, Subscription]:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        name=f"u-{suffix}",
        email=f"grace-{suffix}@email.com",
        password="hash",
    )
    db.session.add(user)
    db.session.commit()
    sub = Subscription(
        user_id=user.id,
        plan_code="premium",
        status=SubscriptionStatus.ACTIVE,
        billing_cycle=BillingCycle.MONTHLY,
        provider="asaas",
        provider_customer_id=f"cust_{suffix}",
    )
    db.session.add(sub)
    db.session.commit()
    sync_entitlements_from_subscription(sub)
    db.session.commit()
    return user, sub


def _has_premium(user_id: uuid.UUID) -> bool:
    return (
        Entitlement.query.filter_by(
            user_id=user_id, feature_key=_PREMIUM_FEATURE
        ).first()
        is not None
    )


def test_payment_failed_opens_grace_and_keeps_premium(app) -> None:
    with app.app_context():
        user, sub = _make_active_premium_user_and_sub()
        assert _has_premium(user.id) is True

        apply_subscription_snapshot(sub, {"status": SubscriptionStatus.PAST_DUE.value})

        assert sub.status == SubscriptionStatus.PAST_DUE
        assert sub.grace_period_ends_at is not None
        expected = utc_now_naive() + timedelta(days=5)
        assert abs((sub.grace_period_ends_at - expected).total_seconds()) < 120
        # Premium must survive the grace window (no instant downgrade).
        assert _has_premium(user.id) is True


def test_repeated_payment_failed_does_not_extend_grace(app) -> None:
    with app.app_context():
        _user, sub = _make_active_premium_user_and_sub()
        apply_subscription_snapshot(sub, {"status": SubscriptionStatus.PAST_DUE.value})
        first_grace = sub.grace_period_ends_at

        # A second payment_failed while already PAST_DUE must not reset the clock.
        apply_subscription_snapshot(sub, {"status": SubscriptionStatus.PAST_DUE.value})

        assert sub.grace_period_ends_at == first_grace


def test_renewed_during_grace_clears_it_and_keeps_premium(app) -> None:
    with app.app_context():
        user, sub = _make_active_premium_user_and_sub()
        apply_subscription_snapshot(sub, {"status": SubscriptionStatus.PAST_DUE.value})
        assert sub.grace_period_ends_at is not None

        apply_subscription_snapshot(sub, {"status": SubscriptionStatus.ACTIVE.value})

        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.grace_period_ends_at is None
        # Continuous premium — no flicker.
        assert _has_premium(user.id) is True


def test_past_due_without_grace_date_still_revokes(app) -> None:
    """Safety: a legacy PAST_DUE (no grace date) keeps the old immediate revoke."""
    with app.app_context():
        user, sub = _make_active_premium_user_and_sub()
        sub.status = SubscriptionStatus.PAST_DUE
        sub.grace_period_ends_at = None
        db.session.commit()

        sync_entitlements_from_subscription(sub)
        db.session.commit()

        assert _has_premium(user.id) is False


def test_lapsed_grace_downgrades_and_emails(app) -> None:
    from app.services.email_provider import get_email_outbox
    from scripts.process_grace_expirations import process_grace_expirations

    with app.app_context():
        user, sub = _make_active_premium_user_and_sub()
        # Force a PAST_DUE whose grace already lapsed.
        sub.status = SubscriptionStatus.PAST_DUE
        sub.grace_period_ends_at = utc_now_naive() - timedelta(days=1)
        db.session.commit()

        count = process_grace_expirations(dry_run=False, flask_app=app)

        assert count == 1
        refreshed = Subscription.query.filter_by(id=sub.id).first()
        assert refreshed is not None
        assert refreshed.status == SubscriptionStatus.EXPIRED
        assert _has_premium(user.id) is False
        assert any(m["tag"] == "billing_grace_expired" for m in get_email_outbox())


def test_lapsed_grace_dry_run_makes_no_change(app) -> None:
    from scripts.process_grace_expirations import process_grace_expirations

    with app.app_context():
        _user, sub = _make_active_premium_user_and_sub()
        sub.status = SubscriptionStatus.PAST_DUE
        sub.grace_period_ends_at = utc_now_naive() - timedelta(days=1)
        db.session.commit()

        count = process_grace_expirations(dry_run=True, flask_app=app)

        assert count == 1
        refreshed = Subscription.query.filter_by(id=sub.id).first()
        assert refreshed is not None
        assert refreshed.status == SubscriptionStatus.PAST_DUE
