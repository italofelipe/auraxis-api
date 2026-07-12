"""Trial-ending reminders — D-2 dunning dispatch service (#1555).

Mirrors the pattern of ``email_verification_reminder_service`` but targets
``Subscription`` rows in ``TRIALING`` status whose ``trial_ends_at`` falls
``days_until_trial_end`` days from ``today``.

Idempotency uses the ``Alert`` table with ``entity_type='subscription'`` and
``entity_id=subscription.id``: once a reminder is recorded for a subscription
and window, it is never sent again — safe against reruns and boundary drift.

Email content lives in ``billing_email_service.build_trial_ending_email`` so
all billing dunning copy stays in one module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence, cast
from uuid import UUID

from app.application.services.billing_email_service import build_trial_ending_email
from app.extensions.database import db
from app.models.alert import Alert, AlertStatus
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services.email_dlq import get_email_dlq
from app.services.email_provider import (
    EmailMessage,
    EmailProviderError,
    get_default_email_provider,
)
from app.utils.datetime_utils import utc_now_naive

_CATEGORY_TEMPLATE = "billing_trial_ending_{days}d"
_SUBSCRIPTION_ENTITY_TYPE = "subscription"


@dataclass(frozen=True)
class TrialEndingReminderResult:
    scanned: int
    sent: int
    skipped: int
    queued: int = 0


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time())


def _end_of_day(day: date) -> datetime:
    return datetime.combine(day, datetime.max.time())


def _existing_alert(
    *, user_id: UUID, category: str, subscription_id: UUID
) -> Alert | None:
    return cast(
        Alert | None,
        Alert.query.filter(
            Alert.user_id == user_id,
            Alert.category == category,
            Alert.entity_type == _SUBSCRIPTION_ENTITY_TYPE,
            Alert.entity_id == subscription_id,
        ).first(),
    )


def _eligible_subscriptions(*, target_day: date) -> Sequence[tuple[Subscription, User]]:
    return cast(
        Sequence[tuple[Subscription, User]],
        db.session.query(Subscription, User)
        .join(User, User.id == Subscription.user_id)
        .filter(
            Subscription.status == SubscriptionStatus.TRIALING,
            Subscription.trial_ends_at.isnot(None),
            Subscription.trial_ends_at >= _start_of_day(target_day),
            Subscription.trial_ends_at <= _end_of_day(target_day),
            User.deleted_at.is_(None),
        )
        .all(),
    )


def _send_or_queue(message: EmailMessage) -> AlertStatus:
    try:
        get_default_email_provider().send(message)
        return AlertStatus.SENT
    except EmailProviderError as exc:
        get_email_dlq().push(message, reason=str(exc))
        return AlertStatus.PENDING


def dispatch_trial_ending_reminders(
    *, days_until_trial_end: int = 2, today: date | None = None
) -> TrialEndingReminderResult:
    """Send "trial acabando" reminders for trials ending in N days.

    Args:
        days_until_trial_end: countdown window in days (default 2 → D-2).
        today: Override the reference day for tests.

    Returns:
        TrialEndingReminderResult with scan/send/skip/queue counters.
    """
    if days_until_trial_end < 1:
        raise ValueError("days_until_trial_end must be >= 1")

    category = _CATEGORY_TEMPLATE.format(days=days_until_trial_end)
    reference_day = today or date.today()
    target_day = reference_day + timedelta(days=days_until_trial_end)

    scanned = 0
    sent = 0
    skipped = 0
    queued = 0

    for subscription, user in _eligible_subscriptions(target_day=target_day):
        scanned += 1
        if _existing_alert(
            user_id=user.id, category=category, subscription_id=subscription.id
        ):
            skipped += 1
            continue

        message = build_trial_ending_email(
            user=user,
            subscription=subscription,
            days_until_trial_end=days_until_trial_end,
        )
        alert_status = _send_or_queue(message)
        if alert_status == AlertStatus.SENT:
            sent += 1
            sent_at = utc_now_naive()
        else:
            queued += 1
            sent_at = None

        db.session.add(
            Alert(
                user_id=user.id,
                category=category,
                status=alert_status,
                entity_type=_SUBSCRIPTION_ENTITY_TYPE,
                entity_id=subscription.id,
                triggered_at=_start_of_day(reference_day),
                sent_at=sent_at,
            )
        )

    db.session.commit()
    return TrialEndingReminderResult(
        scanned=scanned, sent=sent, skipped=skipped, queued=queued
    )


__all__ = [
    "TrialEndingReminderResult",
    "dispatch_trial_ending_reminders",
]
