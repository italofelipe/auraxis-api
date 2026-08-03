"""#1597 — plan upgrade/downgrade without double-charging.

The safety invariant: the current subscription is canceled at the gateway BEFORE
the new checkout is created, so a monthly↔annual switch never leaves two active
subscriptions billing in parallel. Entitlements stay continuous (local state is
untouched; the new plan lands via the completed webhook).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.config.billing_plans import resolve_checkout_plan_offer
from app.extensions.database import db
from app.models.audit_event import AuditEvent
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User
from app.services.billing_adapter import BillingCheckoutCustomer, BillingProviderError
from app.services.subscription_service import change_subscription_plan

_ANNUAL = resolve_checkout_plan_offer("premium_annual")


class _FakeProvider:
    def __init__(
        self, *, cancel_raises: bool = False, checkout: dict[str, Any] | None = None
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self._cancel_raises = cancel_raises
        self._checkout = checkout or {
            "checkout_url": "https://pay.test/bill_new",
            "provider": "asaas",
            "provider_customer_id": "cust_new",
            "provider_subscription_id": "bill_new",
        }

    def cancel_subscription(self, provider_id: str) -> dict[str, Any]:
        self.calls.append(("cancel", provider_id))
        if self._cancel_raises:
            raise BillingProviderError("cancel failed")
        return {"status": "canceled"}

    def create_checkout_session(
        self,
        *,
        customer: BillingCheckoutCustomer,
        plan_slug: str,
        return_surface: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("checkout", plan_slug))
        return self._checkout

    def get_subscription(self, provider_id: str) -> dict[str, Any]:
        return {"status": "active"}


def _make_active_sub(provider_sub_id: str) -> tuple[User, Subscription]:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        name=f"u-{suffix}",
        email=f"pc-{suffix}@email.com",
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
        provider_subscription_id=provider_sub_id,
        provider_customer_id=f"cust_{suffix}",
    )
    db.session.add(sub)
    db.session.commit()
    return user, sub


def _customer(user: User) -> BillingCheckoutCustomer:
    return BillingCheckoutCustomer(
        user_id=str(user.id), name=str(user.name), email=str(user.email)
    )


def test_change_plan_cancels_old_before_new_checkout(app) -> None:
    with app.app_context():
        user, sub = _make_active_sub("subs_old")
        fake = _FakeProvider()

        result = change_subscription_plan(sub, fake, _ANNUAL, _customer(user))

        # Cancel must precede checkout — never two active subscriptions.
        assert [c[0] for c in fake.calls] == ["cancel", "checkout"]
        assert fake.calls[0][1] == "subs_old"
        assert fake.calls[1][1] == "premium_annual"
        assert result["checkout_url"] == "https://pay.test/bill_new"
        # Continuity: local state untouched; pointed at the new placeholder.
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.plan_code == "premium"
        assert sub.billing_cycle == BillingCycle.MONTHLY
        assert sub.provider_subscription_id == "bill_new"


def test_change_plan_skips_cancel_for_bill_placeholder(app) -> None:
    with app.app_context():
        user, sub = _make_active_sub("bill_pending")
        fake = _FakeProvider()

        change_subscription_plan(sub, fake, _ANNUAL, _customer(user))

        # A bill_ placeholder has no active billing to cancel.
        assert [c[0] for c in fake.calls] == ["checkout"]


def test_change_plan_aborts_when_cancel_fails(app) -> None:
    with app.app_context():
        user, sub = _make_active_sub("subs_old")
        fake = _FakeProvider(cancel_raises=True)

        with pytest.raises(BillingProviderError):
            change_subscription_plan(sub, fake, _ANNUAL, _customer(user))

        # New checkout was never created → no double charge; state untouched.
        assert [c[0] for c in fake.calls] == ["cancel"]
        assert sub.provider_subscription_id == "subs_old"


def test_change_plan_records_audit(app, monkeypatch) -> None:
    monkeypatch.setenv("AUDIT_PERSISTENCE_ENABLED", "true")
    with app.app_context():
        user, sub = _make_active_sub("subs_old")
        fake = _FakeProvider()

        change_subscription_plan(sub, fake, _ANNUAL, _customer(user))

        events = AuditEvent.query.filter_by(
            entity_id=str(sub.id), action="plan_change"
        ).all()
        assert len(events) == 1
        assert events[0].extra == "to=premium_annual"


# ── REST surface ────────────────────────────────────────────────────────────


def _register_active_premium(app, client) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"rest-pc-{suffix}@email.com"
    resp = client.post(
        "/auth/register",
        json={"name": f"u-{suffix}", "email": email, "password": "StrongPass@123"},
    )
    assert resp.status_code == 201
    login = client.post(
        "/auth/login", json={"email": email, "password": "StrongPass@123"}
    )
    token = login.get_json()["token"]
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        sub = Subscription.query.filter_by(user_id=user.id).first()
        if sub is None:
            sub = Subscription(
                user_id=user.id, plan_code="free", status=SubscriptionStatus.FREE
            )
            db.session.add(sub)
        sub.status = SubscriptionStatus.ACTIVE
        sub.plan_code = "premium"
        sub.billing_cycle = BillingCycle.MONTHLY
        sub.provider = "asaas"
        sub.provider_subscription_id = "subs_rest_old"
        db.session.commit()
    return token


def test_rest_change_plan_happy_path(app, client, monkeypatch) -> None:
    fake = _FakeProvider()
    monkeypatch.setattr(
        "app.controllers.subscription_controller.get_default_billing_provider",
        lambda: fake,
    )
    token = _register_active_premium(app, client)

    resp = client.post(
        "/subscriptions/change-plan",
        json={"plan_slug": "premium", "billing_cycle": "annual"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["billing_cycle"] == "annual"
    assert data["checkout_url"] == "https://pay.test/bill_new"
    assert [c[0] for c in fake.calls] == ["cancel", "checkout"]


def test_rest_change_plan_same_plan_conflicts(app, client, monkeypatch) -> None:
    fake = _FakeProvider()
    monkeypatch.setattr(
        "app.controllers.subscription_controller.get_default_billing_provider",
        lambda: fake,
    )
    token = _register_active_premium(app, client)

    resp = client.post(
        "/subscriptions/change-plan",
        json={"plan_slug": "premium", "billing_cycle": "monthly"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 409
    # Guarded before touching the gateway.
    assert fake.calls == []


def test_rest_change_plan_invalid_plan(app, client, monkeypatch) -> None:
    token = _register_active_premium(app, client)

    resp = client.post(
        "/subscriptions/change-plan",
        json={"plan_slug": "does_not_exist"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 400
