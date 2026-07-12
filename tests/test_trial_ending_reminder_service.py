"""Tests for trial_ending_reminder_service (#1555 — dunning D-2).

Covers:
- Happy path D-2 dispatch for TRIALING subscription ending in 2 days
- Idempotency: running twice does not duplicate emails (Alert dedupe)
- Skip non-TRIALING subscriptions inside the window
- Skip subscriptions outside the target window
- Skip soft-deleted users
- Invalid window raises ValueError
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.application.services.trial_ending_reminder_service import (
    TrialEndingReminderResult,
    dispatch_trial_ending_reminders,
)
from app.extensions.database import db
from app.models.alert import Alert
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services.email_provider import get_email_outbox

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_with_trial(
    *,
    trial_ends_at: datetime | None,
    status: SubscriptionStatus = SubscriptionStatus.TRIALING,
    deleted_at: datetime | None = None,
) -> tuple[User, Subscription]:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        name=f"Trial {suffix}",
        email=f"trial-{suffix}@test.com",
        password="hash",
        deleted_at=deleted_at,
    )
    db.session.add(user)
    db.session.flush()
    subscription = Subscription(
        user_id=user.id,
        plan_code="trial",
        status=status,
        trial_ends_at=trial_ends_at,
    )
    db.session.add(subscription)
    db.session.commit()
    return user, subscription


def _drain_outbox() -> None:
    get_email_outbox().clear()


def _at_hour(day: date, hour: int) -> datetime:
    return datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_dispatches_d2_reminder_for_trial_ending_in_two_days(app) -> None:
    today = date(2030, 6, 15)
    with app.app_context():
        user, subscription = _make_user_with_trial(
            trial_ends_at=_at_hour(today + timedelta(days=2), 10),
        )
        result = dispatch_trial_ending_reminders(days_until_trial_end=2, today=today)

        assert isinstance(result, TrialEndingReminderResult)
        assert result.scanned == 1
        assert result.sent == 1
        outbox = get_email_outbox()
        assert len(outbox) == 1
        assert outbox[0]["email"] == str(user.email)
        assert outbox[0]["tag"] == "billing_trial_ending_2d"

        alert = Alert.query.filter_by(
            user_id=user.id, category="billing_trial_ending_2d"
        ).first()
        assert alert is not None
        assert alert.entity_type == "subscription"
        assert alert.entity_id == subscription.id
        _drain_outbox()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_is_idempotent_across_runs(app) -> None:
    today = date(2030, 6, 15)
    with app.app_context():
        _make_user_with_trial(
            trial_ends_at=_at_hour(today + timedelta(days=2), 10),
        )
        first = dispatch_trial_ending_reminders(days_until_trial_end=2, today=today)
        second = dispatch_trial_ending_reminders(days_until_trial_end=2, today=today)

        assert first.sent == 1
        assert second.sent == 0
        assert second.skipped == 1
        assert len(get_email_outbox()) == 1
        _drain_outbox()


# ---------------------------------------------------------------------------
# Skip cases
# ---------------------------------------------------------------------------


def test_skips_non_trialing_subscription(app) -> None:
    today = date(2030, 6, 15)
    with app.app_context():
        _make_user_with_trial(
            trial_ends_at=_at_hour(today + timedelta(days=2), 10),
            status=SubscriptionStatus.ACTIVE,
        )
        result = dispatch_trial_ending_reminders(days_until_trial_end=2, today=today)

        assert result.scanned == 0
        assert result.sent == 0
        assert len(get_email_outbox()) == 0


def test_skips_trial_outside_target_window(app) -> None:
    today = date(2030, 6, 15)
    with app.app_context():
        _make_user_with_trial(
            trial_ends_at=_at_hour(today + timedelta(days=5), 10),
        )
        result = dispatch_trial_ending_reminders(days_until_trial_end=2, today=today)

        assert result.scanned == 0
        assert result.sent == 0


def test_skips_soft_deleted_user(app) -> None:
    today = date(2030, 6, 15)
    with app.app_context():
        _make_user_with_trial(
            trial_ends_at=_at_hour(today + timedelta(days=2), 10),
            deleted_at=_at_hour(today - timedelta(days=1), 8),
        )
        result = dispatch_trial_ending_reminders(days_until_trial_end=2, today=today)

        assert result.scanned == 0
        assert result.sent == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_window_raises_value_error(app) -> None:
    with app.app_context():
        with pytest.raises(ValueError):
            dispatch_trial_ending_reminders(days_until_trial_end=0)
