"""#1600 — reconcile local subscriptions against the gateway (lost-webhook drift)."""

from __future__ import annotations

import uuid
from typing import Any

from app.extensions.database import db
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User
from scripts.reconcile_subscriptions import reconcile_subscriptions


class _FakeProvider:
    def __init__(
        self,
        snapshots: dict[str, dict[str, Any]] | None = None,
        raise_for: set[str] | None = None,
    ) -> None:
        self._snapshots = snapshots or {}
        self._raise_for = raise_for or set()

    def get_subscription(self, provider_id: str) -> dict[str, Any]:
        if provider_id in self._raise_for:
            raise RuntimeError("gateway unavailable")
        return self._snapshots.get(provider_id, {"status": "active"})


def _make_sub(status: SubscriptionStatus, provider_id: str | None) -> Subscription:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        name=f"u-{suffix}",
        email=f"recon-{suffix}@email.com",
        password="hash",
    )
    db.session.add(user)
    db.session.commit()
    sub = Subscription(
        user_id=user.id,
        plan_code="premium",
        status=status,
        billing_cycle=BillingCycle.MONTHLY,
        provider="asaas",
        provider_subscription_id=provider_id,
        provider_customer_id=f"cust_{suffix}",
    )
    db.session.add(sub)
    db.session.commit()
    return sub


def _patch_provider(monkeypatch, provider: _FakeProvider) -> None:
    monkeypatch.setattr(
        "app.services.billing_adapter.get_default_billing_provider",
        lambda: provider,
    )


def test_reconcile_corrects_drift(app, monkeypatch) -> None:
    with app.app_context():
        sub = _make_sub(SubscriptionStatus.ACTIVE, "subs_1")
        _patch_provider(monkeypatch, _FakeProvider({"subs_1": {"status": "canceled"}}))

        summary = reconcile_subscriptions(dry_run=False, flask_app=app)

        assert summary == {"checked": 1, "reconciled": 1, "errors": 0}
        refreshed = Subscription.query.filter_by(id=sub.id).first()
        assert refreshed is not None
        assert refreshed.status == SubscriptionStatus.CANCELED


def test_reconcile_noop_when_in_sync(app, monkeypatch) -> None:
    with app.app_context():
        sub = _make_sub(SubscriptionStatus.ACTIVE, "subs_1")
        _patch_provider(monkeypatch, _FakeProvider({"subs_1": {"status": "active"}}))

        summary = reconcile_subscriptions(dry_run=False, flask_app=app)

        assert summary == {"checked": 1, "reconciled": 0, "errors": 0}
        refreshed = Subscription.query.filter_by(id=sub.id).first()
        assert refreshed is not None
        assert refreshed.status == SubscriptionStatus.ACTIVE


def test_reconcile_skips_provider_errors(app, monkeypatch) -> None:
    with app.app_context():
        _make_sub(SubscriptionStatus.ACTIVE, "subs_1")
        _patch_provider(monkeypatch, _FakeProvider(raise_for={"subs_1"}))

        summary = reconcile_subscriptions(dry_run=False, flask_app=app)

        assert summary == {"checked": 1, "reconciled": 0, "errors": 1}


def test_reconcile_dry_run_detects_but_does_not_apply(app, monkeypatch) -> None:
    with app.app_context():
        sub = _make_sub(SubscriptionStatus.ACTIVE, "subs_1")
        _patch_provider(monkeypatch, _FakeProvider({"subs_1": {"status": "canceled"}}))

        summary = reconcile_subscriptions(dry_run=True, flask_app=app)

        assert summary == {"checked": 1, "reconciled": 1, "errors": 0}
        refreshed = Subscription.query.filter_by(id=sub.id).first()
        assert refreshed is not None
        assert refreshed.status == SubscriptionStatus.ACTIVE


def test_reconcile_skips_bill_placeholder(app, monkeypatch) -> None:
    with app.app_context():
        _make_sub(SubscriptionStatus.ACTIVE, "bill_not_yet_real")
        _patch_provider(monkeypatch, _FakeProvider())

        summary = reconcile_subscriptions(dry_run=False, flask_app=app)

        assert summary == {"checked": 0, "reconciled": 0, "errors": 0}
