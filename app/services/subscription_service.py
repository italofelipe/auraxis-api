"""Subscription service — J9 (billing / plan management).

Encapsulates all business logic for reading and mutating subscription state,
keeping controllers thin and provider-agnostic.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from flask import current_app, has_app_context

from app.config.billing_plans import (
    BillingPlanOffer,
    parse_billing_cycle,
    resolve_checkout_plan_offer,
)
from app.config.plan_features import PLAN_FEATURES
from app.extensions.database import db
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User
from app.services.billing_adapter import (
    BillingCheckoutCustomer,
    BillingCheckoutSession,
    BillingProvider,
    BillingSubscriptionSnapshot,
)
from app.services.entitlement_service import sync_entitlements_from_subscription
from app.utils.datetime_utils import utc_now_naive

logger = logging.getLogger(__name__)

_FREE_PLAN_CODE = "free"
_PREMIUM_OVERRIDE_USER_IDS_CONFIG_KEY = "AURAXIS_PREMIUM_OVERRIDE_USER_IDS"
_ENV_OVERRIDE_REASON = "Migrated from AURAXIS_PREMIUM_OVERRIDE_USER_IDS"
_ENV_OVERRIDE_ACTOR = "system:legacy-premium-override-env"


def _premium_override_user_ids_config() -> str:
    if has_app_context():
        configured = current_app.config.get(_PREMIUM_OVERRIDE_USER_IDS_CONFIG_KEY)
        if configured is not None:
            return str(configured)
    return os.getenv(_PREMIUM_OVERRIDE_USER_IDS_CONFIG_KEY, "")


def configured_premium_override_user_ids() -> frozenset[UUID]:
    configured_user_ids: set[UUID] = set()
    raw_config = _premium_override_user_ids_config()
    for token in raw_config.replace(";", ",").split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            configured_user_ids.add(UUID(candidate))
        except ValueError:
            continue
    return frozenset(configured_user_ids)


def is_premium_override_user_id(user_id: UUID) -> bool:
    return user_id in configured_premium_override_user_ids()


def ensure_premium_override_subscription(
    user_id: UUID,
    *,
    subscription: Subscription | None = None,
) -> Subscription | None:
    """Migrate a configured legacy override without touching billing state.

    The environment fallback remains temporarily available during rollout, but
    its first use creates the same auditable ``premium_overrides`` record used by
    the control plane. The user's subscription, plan and provider state are never
    changed.
    """
    user = cast(User | None, db.session.get(User, user_id))
    if user is None or not is_premium_override_user_id(user_id):
        return None

    from app.services.premium_override_service import (
        get_active_premium_override,
        grant_premium_override,
    )

    if get_active_premium_override(user_id) is None:
        grant_premium_override(
            user_id=user_id,
            reason=_ENV_OVERRIDE_REASON,
            granted_by=_ENV_OVERRIDE_ACTOR,
        )
        db.session.commit()

    if subscription is None:
        subscription = cast(
            Subscription | None,
            Subscription.query.filter_by(user_id=user_id).first(),
        )
    return subscription


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
    return (
        ensure_premium_override_subscription(
            user_id,
            subscription=subscription,
        )
        or subscription
    )


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


def _set_nullable_datetime_if_changed(
    current: datetime | None,
    next_value: datetime | None,
) -> tuple[datetime | None, bool]:
    if current == next_value:
        return current, False
    return next_value, True


def _grace_period_days() -> int:
    """Dunning grace window (#1599). Configurable; defaults to 5 days."""
    default = 5
    if has_app_context():
        return int(current_app.config.get("BILLING_GRACE_PERIOD_DAYS", default))
    return int(os.getenv("BILLING_GRACE_PERIOD_DAYS", str(default)))


def _apply_grace_transition(
    subscription: Subscription,
    *,
    status_changed: bool,
    next_status: SubscriptionStatus | None,
) -> None:
    """#1599: manage the dunning grace window on status transitions.

    Entering PAST_DUE opens a grace window so premium stays on during payment
    retries; entering ACTIVE clears it (a renewal keeps premium continuous). A
    repeated payment_failed does not extend an already-open window.
    """
    if not status_changed or next_status is None:
        return
    if next_status == SubscriptionStatus.PAST_DUE:
        if subscription.grace_period_ends_at is None:
            subscription.grace_period_ends_at = utc_now_naive() + timedelta(
                days=_grace_period_days()
            )
    elif next_status == SubscriptionStatus.ACTIVE:
        subscription.grace_period_ends_at = None


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
    subscription.status, status_changed = _set_if_changed(
        subscription.status, next_status
    )
    changed = changed or status_changed

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

    # #1569: the gateway owns the trial window now, so trial_ends_at follows the
    # provider. Only set when present — a renewal payload carries no trial data
    # and must not wipe the date the trial_started event recorded.
    trial_ends_at = snapshot.get("trial_ends_at")
    if trial_ends_at is not None:
        subscription.trial_ends_at, did_change = _set_if_changed(
            subscription.trial_ends_at, trial_ends_at
        )
        changed = changed or did_change

    _apply_grace_transition(
        subscription, status_changed=status_changed, next_status=next_status
    )
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
        return (
            ensure_premium_override_subscription(
                subscription.user_id,
                subscription=subscription,
            )
            or subscription
        )

    data = provider.get_subscription(subscription.provider_subscription_id)
    subscription = apply_subscription_snapshot(subscription, data)
    return (
        ensure_premium_override_subscription(
            subscription.user_id,
            subscription=subscription,
        )
        or subscription
    )


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
    if not snapshot.provider_subscription_id:
        _dispatch_local_cancellation_email(snapshot)
    return snapshot


def change_subscription_plan(
    subscription: Subscription,
    provider: BillingProvider,
    new_offer: BillingPlanOffer,
    customer: BillingCheckoutCustomer,
) -> BillingCheckoutSession:
    """Swap the active plan without ever double-charging (#1597).

    Ordering is the safety guarantee: the current subscription is canceled at the
    gateway **before** the new checkout is created, so there are never two active
    subscriptions billing in parallel. If the cancel raises, the new checkout is
    never created — no double charge.

    Entitlements stay continuous: local ``status``, ``plan_code`` and
    ``current_period_end`` are left untouched, so the user keeps premium on the
    period they already paid for; the new plan lands when the gateway delivers the
    ``subscription.completed`` webhook. The local record is pointed at the new
    ``bill_`` placeholder so the reconciliation job (#1600) skips it until then.
    If the user abandons the new checkout, entitlements simply expire at the old
    period end — no indefinite free premium.

    Returns the new checkout session (hosted URL for the user to pay).
    """
    from app.extensions.audit_trail import record_entity_change

    old_provider_id = subscription.provider_subscription_id
    # 1. Cancel the current subscription at the gateway FIRST. Only a real
    #    ``subs_`` id has active billing — a ``bill_`` placeholder (an earlier
    #    unpaid swap/checkout) has nothing to cancel.
    if old_provider_id and not old_provider_id.startswith("bill_"):
        provider.cancel_subscription(old_provider_id)

    # 2. Only now create the new checkout. A failure here leaves the user on their
    #    already-paid period (premium intact) and never double-charged.
    result = provider.create_checkout_session(
        customer=customer, plan_slug=new_offer.slug
    )

    # 3. Point the local record at the new bill_ placeholder; leave status/plan/
    #    period untouched so premium is continuous and reconciliation skips it
    #    until the completed webhook promotes the real subscription id + plan.
    new_provider_id = result.get("provider_subscription_id")
    if isinstance(new_provider_id, str) and new_provider_id.strip():
        subscription.provider_subscription_id = new_provider_id.strip()
    provider_name = str(result.get("provider") or "").strip()
    if provider_name:
        subscription.provider = provider_name
    provider_customer_id = result.get("provider_customer_id")
    if isinstance(provider_customer_id, str) and provider_customer_id.strip():
        subscription.provider_customer_id = provider_customer_id.strip()
    db.session.commit()

    record_entity_change(
        entity_type="subscription",
        entity_id=str(subscription.id),
        actor_id=str(subscription.user_id),
        action="plan_change",
        extra=f"to={new_offer.slug}",
    )
    return result


def _dispatch_local_cancellation_email(subscription: Subscription) -> None:
    """Send the cancellation confirmation for local-only cancels (#1555).

    Provider-backed subscriptions get their confirmation via the
    ``SUBSCRIPTION_DELETED`` webhook; local-only subscriptions (no
    ``provider_subscription_id``) never receive a webhook, so the email is
    dispatched here. Failures are logged but never block the cancel flow.
    """
    from app.application.services.billing_email_service import dispatch_billing_email

    user = cast(User | None, db.session.get(User, subscription.user_id))
    if user is None:
        return
    try:
        dispatch_billing_email(
            user=user,
            subscription=subscription,
            event_type="subscription.canceled",
        )
    except Exception:
        logger.exception(
            "Failed to dispatch cancellation email for subscription_id=%s",
            str(subscription.id),
        )
