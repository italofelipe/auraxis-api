from __future__ import annotations

import uuid

from app.application.services.billing_email_service import (
    build_trial_ending_email,
    dispatch_billing_email,
    dispatch_trial_expired_email,
)
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User
from app.services.email_provider import EmailMessage, get_email_outbox


def test_billing_email_service_sends_payment_confirmed_email(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Auraxis User",
            email="billing@email.com",
            password="hash",
        )
        subscription = Subscription(
            user_id=user.id,
            plan_code="premium",
            status=SubscriptionStatus.ACTIVE,
            billing_cycle=BillingCycle.MONTHLY,
        )

        dispatch_billing_email(
            user=user,
            subscription=subscription,
            event_type="PAYMENT_RECEIVED",
        )

        outbox = get_email_outbox()
        assert len(outbox) == 1
        assert outbox[0]["email"] == "billing@email.com"
        assert outbox[0]["tag"] == "billing_payment_confirmed"


def test_billing_email_service_sends_payment_failed_email(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Auraxis User",
            email="billing@email.com",
            password="hash",
        )
        subscription = Subscription(
            user_id=user.id,
            plan_code="premium",
            status=SubscriptionStatus.PAST_DUE,
            billing_cycle=BillingCycle.MONTHLY,
        )

        dispatch_billing_email(
            user=user,
            subscription=subscription,
            event_type="PAYMENT_OVERDUE",
        )

        outbox = get_email_outbox()
        assert len(outbox) == 1
        assert outbox[0]["tag"] == "billing_payment_failed"


def test_billing_email_service_sends_subscription_canceled_email(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Auraxis User",
            email="billing@email.com",
            password="hash",
        )
        subscription = Subscription(
            user_id=user.id,
            plan_code="premium",
            status=SubscriptionStatus.CANCELED,
            billing_cycle=BillingCycle.MONTHLY,
        )

        dispatch_billing_email(
            user=user,
            subscription=subscription,
            event_type="SUBSCRIPTION_DELETED",
        )

        outbox = get_email_outbox()
        assert len(outbox) == 1
        assert outbox[0]["tag"] == "billing_subscription_canceled"


def test_build_trial_ending_email_returns_ready_message(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Auraxis User",
            email="trial@email.com",
            password="hash",
        )
        subscription = Subscription(
            user_id=user.id,
            plan_code="trial",
            status=SubscriptionStatus.TRIALING,
        )

        message = build_trial_ending_email(
            user=user,
            subscription=subscription,
            days_until_trial_end=2,
        )

        assert isinstance(message, EmailMessage)
        assert message.to_email == "trial@email.com"
        assert message.tag == "billing_trial_ending_2d"
        assert "2 dias" in message.subject
        assert "2 dias" in message.text


def test_dispatch_trial_expired_email_sends_downgrade_notice(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Auraxis User",
            email="expired@email.com",
            password="hash",
        )
        subscription = Subscription(
            user_id=user.id,
            plan_code="free",
            status=SubscriptionStatus.FREE,
        )

        dispatch_trial_expired_email(user=user, subscription=subscription)

        outbox = get_email_outbox()
        assert len(outbox) == 1
        assert outbox[0]["email"] == "expired@email.com"
        assert outbox[0]["tag"] == "billing_trial_expired"
