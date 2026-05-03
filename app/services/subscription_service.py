"""Subscription service — J9 (billing / plan management).

Encapsulates all business logic for reading and mutating subscription state,
keeping controllers thin and provider-agnostic.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

from app.config.billing_plans import parse_billing_cycle, resolve_checkout_plan_offer
from app.config.plan_features import PLAN_FEATURES
from app.extensions.database import db
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User
from app.services.billing_adapter import BillingProvider, BillingSubscriptionSnapshot
from app.services.entitlement_service import sync_entitlements_from_subscription

_FREE_PLAN_CODE = "free"


def _normalize_plan_snapshot(
    *,
    raw_plan_code: object,
    raw_billing_cycle: object,
    raw_offer_code: object,
) -> tuple[str, BillingCycle | None] | None:
    offer = resolve_checkout_plan_offer(
        str(raw_offer_code or raw_plan_code or "").strip().lower()
    )
    if offer is not None:
        return offer.plan_code, offer.billing_cycle

    normalized_plan = str(raw_plan_code or "").strip().lower()
    if normalized_plan not in PLAN_FEATURES:
        return None

    return normalized_plan, parse_billing_cycle(str(raw_billing_cycle or ""))


def get_or_create_subscription(user_id: UUID) -> Subscription:
    """Return the active Subscription for *user_id*.

    Creates a free-tier record if none exists yet.
    """
    subscription = cast(
        Subscription | None,
        Subscription.query.filter_by(user_id=user_id).first(),
    )
    if subscription is None:
        subscription = Subscription(
            user_id=user_id,
            plan_code=_FREE_PLAN_CODE,
            status=SubscriptionStatus.FREE,
        )
        db.session.add(subscription)
        db.session.commit()
    return subscription


def _bump_entitlements_version(user_id: UUID) -> None:
    user = cast(User | None, db.session.get(User, user_id))
    if user is None:
        return
    user.entitlements_version = int(user.entitlements_version or 0) + 1


def _sync_access_if_needed(subscription: Subscription, *, changed: bool) -> None:
    if not changed:
        return
    sync_entitlements_from_subscription(subscription)
    _bump_entitlements_version(subscription.user_id)


def _set_if_changed[T](current: T, next_value: T | None) -> tuple[T, bool]:
    if next_value is None or current == next_value:
        return current, False
    return next_value, True


def apply_subscription_snapshot(
    subscription: Subscription,
    snapshot: BillingSubscriptionSnapshot,
) -> Subscription:
    """Apply provider data to *subscription* and sync entitlement side effects."""

    changed = False

    raw_status = snapshot.get("status", "")
    try:
        next_status = SubscriptionStatus(str(raw_status))
    except ValueError:
        next_status = None
    subscription.status, did_change = _set_if_changed(subscription.status, next_status)
    changed = changed or did_change

    normalized_plan = _normalize_plan_snapshot(
        raw_plan_code=snapshot.get("plan_code"),
        raw_billing_cycle=snapshot.get("billing_cycle"),
        raw_offer_code=snapshot.get("offer_code"),
    )
    if normalized_plan is not None:
        next_plan_code, next_billing_cycle = normalized_plan
        subscription.plan_code, did_change = _set_if_changed(
            subscription.plan_code, next_plan_code
        )
        changed = changed or did_change
        subscription.billing_cycle, did_change = _set_if_changed(
            subscription.billing_cycle, next_billing_cycle
        )
        changed = changed or did_change

    provider = snapshot.get("provider")
    subscription.provider, did_change = _set_if_changed(subscription.provider, provider)
    changed = changed or did_change

    provider_id = snapshot.get("provider_id")
    subscription.provider_subscription_id, did_change = _set_if_changed(
        subscription.provider_subscription_id, provider_id
    )
    changed = changed or did_change

    provider_customer_id = snapshot.get("provider_customer_id")
    subscription.provider_customer_id, did_change = _set_if_changed(
        subscription.provider_customer_id, provider_customer_id
    )
    changed = changed or did_change

    next_period_start = snapshot.get("current_period_start")
    subscription.current_period_start, did_change = _set_if_changed(
        subscription.current_period_start, next_period_start
    )
    changed = changed or did_change

    next_period_end = snapshot.get("current_period_end")
    subscription.current_period_end, did_change = _set_if_changed(
        subscription.current_period_end, next_period_end
    )
    changed = changed or did_change

    _sync_access_if_needed(subscription, changed=changed)
    db.session.commit()
    return subscription


def sync_subscription_from_provider(
    subscription: Subscription,
    provider: BillingProvider,
) -> Subscription:
    """Pull the latest state from *provider* and persist it to *subscription*.

    Only performs an update when the subscription has a ``provider_subscription_id``
    set; otherwise the record is returned unchanged (free-tier users have no
    provider-side subscription to sync).
    """
    if not subscription.provider_subscription_id:
        return subscription

    data = provider.get_subscription(subscription.provider_subscription_id)
    return apply_subscription_snapshot(subscription, data)


def cancel_subscription(
    subscription: Subscription,
    provider: BillingProvider,
) -> Subscription:
    """Cancel *subscription* in both the provider and the local database.

    If the subscription has no provider ID the status is set to CANCELED locally
    without making a provider call.
    """
    from app.extensions.audit_trail import record_entity_delete

    if subscription.provider_subscription_id:
        provider.cancel_subscription(subscription.provider_subscription_id)

    snapshot = apply_subscription_snapshot(
        subscription,
        {
            "status": SubscriptionStatus.CANCELED.value,
            "provider_customer_id": subscription.provider_customer_id,
            **({"provider": subscription.provider} if subscription.provider else {}),
            **(
                {"provider_id": subscription.provider_subscription_id}
                if subscription.provider_subscription_id
                else {}
            ),
        },
    )
    record_entity_delete(
        entity_type="subscription",
        entity_id=str(snapshot.id),
        actor_id=str(snapshot.user_id),
    )
    return snapshot
