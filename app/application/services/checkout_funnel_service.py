"""Checkout funnel — recording attempts and reading the conversion.

Every transition emits a structured log line with a stable ``event=`` marker so
the funnel is answerable from CloudWatch alone, without a database round trip:

    event=checkout_started    event=checkout_completed    event=checkout_failed

The markers matter more than they look. The paid path ran against the sandbox
for ten days without anyone noticing, precisely because success emitted nothing
and the only failure signal was mislabelled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func

from app.extensions.database import db
from app.models.checkout_attempt import CheckoutAttempt, CheckoutAttemptStatus
from app.utils.datetime_utils import utc_now_naive

logger = logging.getLogger(__name__)

# How long a started checkout is given before it counts as abandoned. The gateway
# hands the buyer a hosted page; someone who is going to pay does it in minutes,
# not hours. Kept generous so a slow buyer is not counted as lost.
DEFAULT_ABANDON_AFTER = timedelta(minutes=45)


@dataclass(frozen=True)
class CheckoutFunnel:
    """Counts for a window, split so each number answers one question."""

    started: int
    completed: int
    abandoned: int
    failed: int
    pending: int

    @property
    def conversion_rate(self) -> float:
        """Share of resolved attempts that became a subscription.

        ``pending`` is excluded from the denominator on purpose: an attempt that
        is still inside the abandonment window has not decided yet, and counting
        it as a loss would make the rate dip every time someone opens a checkout.
        """
        resolved = self.completed + self.abandoned + self.failed
        if resolved == 0:
            return 0.0
        return round(self.completed / resolved * 100, 2)


def record_checkout_started(
    *,
    user_id: UUID,
    plan_slug: str,
    plan_code: str | None,
    billing_cycle: str | None,
    provider: str,
    provider_checkout_id: str | None,
    provider_customer_id: str | None,
    return_surface: str | None,
) -> CheckoutAttempt:
    """Persist a started attempt and log it.

    The caller is responsible for committing: the attempt shares the request's
    transaction with the subscription row it updates, so a rollback must not
    leave a phantom attempt behind.

    :param user_id: Buyer.
    :param plan_slug: Offer slug requested.
    :param plan_code: Resolved internal plan code.
    :param billing_cycle: Monthly/annual, when the offer carries one.
    :param provider: Gateway slug.
    :param provider_checkout_id: Gateway checkout id (``bill_…``).
    :param provider_customer_id: Gateway customer id, used to match webhooks.
    :param return_surface: Surface the buyer started from.
    :returns: The unsaved-but-added attempt row.
    """
    attempt = CheckoutAttempt(
        user_id=user_id,
        plan_slug=plan_slug,
        plan_code=plan_code,
        billing_cycle=billing_cycle,
        provider=provider,
        provider_checkout_id=provider_checkout_id,
        provider_customer_id=provider_customer_id,
        return_surface=return_surface,
        status=CheckoutAttemptStatus.STARTED.value,
        started_at=utc_now_naive(),
    )
    db.session.add(attempt)

    logger.info(
        "event=checkout_started user_id=%s plan=%s cycle=%s surface=%s "
        "provider=%s checkout_id=%s",
        user_id,
        plan_slug,
        billing_cycle or "-",
        return_surface or "-",
        provider,
        provider_checkout_id or "-",
    )
    return attempt


def record_checkout_failed(
    *,
    user_id: UUID,
    plan_slug: str,
    provider: str,
    reason: str,
) -> CheckoutAttempt:
    """Persist an attempt the gateway refused, and log it as an error.

    A buyer who never received a payment URL is a lost sale caused by us, not by
    them — it belongs at error level, separate from abandonment.

    :param user_id: Buyer.
    :param plan_slug: Offer slug requested.
    :param provider: Gateway slug.
    :param reason: Short description of the refusal.
    :returns: The unsaved-but-added attempt row.
    """
    attempt = CheckoutAttempt(
        user_id=user_id,
        plan_slug=plan_slug,
        provider=provider,
        status=CheckoutAttemptStatus.STARTED.value,
        started_at=utc_now_naive(),
    )
    attempt.mark_failed(reason=reason)
    db.session.add(attempt)

    logger.error(
        "event=checkout_failed user_id=%s plan=%s provider=%s reason=%s",
        user_id,
        plan_slug,
        provider,
        reason,
    )
    return attempt


def complete_attempt_for_subscription(
    *,
    provider: str,
    provider_customer_id: str | None,
    provider_subscription_id: str | None,
    user_id: UUID | None = None,
) -> CheckoutAttempt | None:
    """Close the attempt that a paid webhook belongs to.

    Matching walks from the most specific handle to the least: the subscription
    id only exists after payment, the checkout/customer id is what the attempt
    was created with, and the user is the last resort. The newest open attempt
    wins — a buyer who retries leaves several, and it is the latest one that got
    paid.

    :param provider: Gateway slug from the webhook.
    :param provider_customer_id: Gateway customer id, when the payload carries one.
    :param provider_subscription_id: Gateway subscription id created by payment.
    :param user_id: Buyer, when already resolved by the caller.
    :returns: The attempt that was closed, or ``None`` when none matched.
    """
    query = CheckoutAttempt.query.filter(
        CheckoutAttempt.status == CheckoutAttemptStatus.STARTED.value,
        CheckoutAttempt.provider == provider,
    )

    candidates = None
    if provider_customer_id:
        candidates = query.filter(
            CheckoutAttempt.provider_customer_id == provider_customer_id
        )
    elif user_id is not None:
        candidates = query.filter(CheckoutAttempt.user_id == user_id)

    if candidates is None:
        logger.warning(
            "event=checkout_completed_unmatched provider=%s subscription_id=%s "
            "reason=no_handle_in_payload",
            provider,
            provider_subscription_id or "-",
        )
        return None

    attempt: CheckoutAttempt | None = candidates.order_by(
        CheckoutAttempt.started_at.desc()
    ).first()
    if attempt is None:
        # Not necessarily a bug: a subscription created outside our checkout
        # (manual override, gateway dashboard) has no attempt to close.
        logger.warning(
            "event=checkout_completed_unmatched provider=%s subscription_id=%s "
            "customer_id=%s reason=no_open_attempt",
            provider,
            provider_subscription_id or "-",
            provider_customer_id or "-",
        )
        return None

    attempt.mark_completed(provider_subscription_id=provider_subscription_id)

    elapsed = (attempt.completed_at - attempt.started_at).total_seconds()
    logger.info(
        "event=checkout_completed user_id=%s plan=%s cycle=%s surface=%s "
        "provider=%s subscription_id=%s seconds_to_pay=%.0f",
        attempt.user_id,
        attempt.plan_slug,
        attempt.billing_cycle or "-",
        attempt.return_surface or "-",
        provider,
        provider_subscription_id or "-",
        elapsed,
    )
    return attempt


def summarize_funnel(
    *,
    since: datetime | None = None,
    abandon_after: timedelta = DEFAULT_ABANDON_AFTER,
    now: datetime | None = None,
    return_surface: str | None = None,
) -> CheckoutFunnel:
    """Count the funnel for a window.

    Abandonment is derived, never stored: it is simply a started attempt older
    than ``abandon_after`` with no completion. Storing it would need a sweep that
    can lag or double-run, and would be a second source of truth for something
    the timestamps already say.

    :param since: Window start; unbounded when omitted.
    :param abandon_after: How long before a started attempt counts as lost.
    :param now: Reference instant, for deterministic tests.
    :param return_surface: Restrict to one surface (landing/app).
    :returns: Counts plus a conversion rate.
    """
    reference = now or utc_now_naive()
    cutoff = reference - abandon_after

    query = db.session.query(
        CheckoutAttempt.status,
        func.count(CheckoutAttempt.id),
        func.sum(db.case((CheckoutAttempt.started_at < cutoff, 1), else_=0)),
    )
    if since is not None:
        query = query.filter(CheckoutAttempt.started_at >= since)
    if return_surface is not None:
        query = query.filter(CheckoutAttempt.return_surface == return_surface)

    completed = failed = abandoned = pending = 0
    for status, total, stale in query.group_by(CheckoutAttempt.status).all():
        stale_count = int(stale or 0)
        if status == CheckoutAttemptStatus.COMPLETED.value:
            completed = int(total)
        elif status == CheckoutAttemptStatus.FAILED.value:
            failed = int(total)
        else:
            abandoned = stale_count
            pending = int(total) - stale_count

    return CheckoutFunnel(
        started=completed + failed + abandoned + pending,
        completed=completed,
        abandoned=abandoned,
        failed=failed,
        pending=pending,
    )
