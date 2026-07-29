"""Tests for the checkout funnel — #1634.

The funnel exists because abandonment had no denominator: ``subscriptions``
carries one row per user with the current state, so an attempt that never becomes
a payment left no trace, and the gateway emits no abandonment event.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.application.services.checkout_funnel_service import (
    CheckoutFunnel,
    complete_attempt_for_subscription,
    record_checkout_failed,
    record_checkout_started,
    summarize_funnel,
)
from app.extensions.database import db
from app.models.checkout_attempt import CheckoutAttempt, CheckoutAttemptStatus
from app.models.user import User
from app.utils.datetime_utils import utc_now_naive


@pytest.fixture
def buyer(app):
    """Persist a user to own the checkout attempts.

    :param app: Flask app fixture providing the DB context.
    :returns: The persisted user.
    """
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Compradora",
            email=f"funnel-{uuid.uuid4().hex[:8]}@auraxis.com.br",
            password="hash",
        )
        db.session.add(user)
        db.session.commit()
        yield user


def _start(user_id, **overrides):
    """Record a started attempt with sensible defaults.

    :param user_id: Buyer id.
    :param overrides: Fields to override.
    :returns: The persisted attempt.
    """
    payload = {
        "plan_slug": "premium_monthly",
        "plan_code": "premium",
        "billing_cycle": "monthly",
        "provider": "abacatepay",
        "provider_checkout_id": f"bill_{uuid.uuid4().hex[:8]}",
        "provider_customer_id": f"cust_{uuid.uuid4().hex[:8]}",
        "return_surface": "landing",
    }
    payload.update(overrides)
    attempt = record_checkout_started(user_id=user_id, **payload)
    db.session.commit()
    return attempt


class TestRecording:
    def test_started_attempt_keeps_the_provider_checkout_id(self, app, buyer):
        """Without the bill id there is nothing to correlate a webhook back to."""
        with app.app_context():
            attempt = _start(buyer.id, provider_checkout_id="bill_abc123")

            assert attempt.status == CheckoutAttemptStatus.STARTED.value
            assert attempt.provider_checkout_id == "bill_abc123"
            assert attempt.return_surface == "landing"
            assert attempt.completed_at is None

    def test_failed_attempt_records_the_reason_and_no_url(self, app, buyer):
        """A refused checkout is a sale lost by us, tracked apart from abandonment."""
        with app.app_context():
            attempt = record_checkout_failed(
                user_id=buyer.id,
                plan_slug="premium_annual",
                provider="abacatepay",
                reason="BILLING_ABACATEPAY_PRODUCT_PREMIUM_ANNUAL is required",
            )
            db.session.commit()

            assert attempt.status == CheckoutAttemptStatus.FAILED.value
            assert "PREMIUM_ANNUAL" in attempt.failure_reason
            assert attempt.provider_checkout_id is None

    def test_failure_reason_is_truncated_to_the_column_width(self, app, buyer):
        """A provider stack trace must not blow up the insert."""
        with app.app_context():
            attempt = record_checkout_failed(
                user_id=buyer.id,
                plan_slug="premium_monthly",
                provider="abacatepay",
                reason="x" * 500,
            )
            db.session.commit()

            assert len(attempt.failure_reason) == 200


class TestCompletion:
    def test_matches_the_attempt_by_provider_customer_id(self, app, buyer):
        """The customer id is the only handle both sides share before payment."""
        with app.app_context():
            attempt = _start(buyer.id, provider_customer_id="cust_match")

            closed = complete_attempt_for_subscription(
                provider="abacatepay",
                provider_customer_id="cust_match",
                provider_subscription_id="subs_999",
            )

            assert closed is not None
            assert closed.id == attempt.id
            assert closed.status == CheckoutAttemptStatus.COMPLETED.value
            assert closed.provider_subscription_id == "subs_999"
            assert closed.completed_at is not None

    def test_closes_the_newest_open_attempt_when_the_buyer_retried(self, app, buyer):
        """A buyer who retries leaves several attempts; the last one got paid."""
        with app.app_context():
            older = _start(buyer.id, provider_customer_id="cust_retry")
            older.started_at = utc_now_naive() - timedelta(hours=2)
            newer = _start(buyer.id, provider_customer_id="cust_retry")
            db.session.commit()

            closed = complete_attempt_for_subscription(
                provider="abacatepay",
                provider_customer_id="cust_retry",
                provider_subscription_id="subs_retry",
            )

            assert closed.id == newer.id
            assert older.status == CheckoutAttemptStatus.STARTED.value

    def test_returns_none_when_no_attempt_exists(self, app, buyer):
        """A subscription created outside our checkout has nothing to close."""
        with app.app_context():
            assert (
                complete_attempt_for_subscription(
                    provider="abacatepay",
                    provider_customer_id="cust_absent",
                    provider_subscription_id="subs_manual",
                )
                is None
            )

    def test_returns_none_when_the_payload_carries_no_handle(self, app, buyer):
        """Without a customer id or a user, matching would be a guess."""
        with app.app_context():
            _start(buyer.id)

            assert (
                complete_attempt_for_subscription(
                    provider="abacatepay",
                    provider_customer_id=None,
                    provider_subscription_id="subs_blind",
                )
                is None
            )

    def test_does_not_reopen_an_already_completed_attempt(self, app, buyer):
        """Provider retries are common; a second webhook must not double-count."""
        with app.app_context():
            _start(buyer.id, provider_customer_id="cust_once")

            first = complete_attempt_for_subscription(
                provider="abacatepay",
                provider_customer_id="cust_once",
                provider_subscription_id="subs_once",
            )
            second = complete_attempt_for_subscription(
                provider="abacatepay",
                provider_customer_id="cust_once",
                provider_subscription_id="subs_once",
            )

            assert first is not None
            assert second is None


class TestFunnelSummary:
    def test_abandonment_is_derived_from_the_cutoff_not_stored(self, app, buyer):
        """The same row counts as pending or abandoned depending on the cutoff."""
        with app.app_context():
            attempt = _start(buyer.id)
            attempt.started_at = utc_now_naive() - timedelta(minutes=30)
            db.session.commit()

            lenient = summarize_funnel(abandon_after=timedelta(minutes=45))
            strict = summarize_funnel(abandon_after=timedelta(minutes=10))

            assert (lenient.pending, lenient.abandoned) == (1, 0)
            assert (strict.pending, strict.abandoned) == (0, 1)

    def test_counts_each_outcome_separately(self, app, buyer):
        """Failed and abandoned have different causes and different owners."""
        with app.app_context():
            stale = _start(buyer.id)
            stale.started_at = utc_now_naive() - timedelta(hours=3)

            _start(buyer.id, provider_customer_id="cust_done")
            complete_attempt_for_subscription(
                provider="abacatepay",
                provider_customer_id="cust_done",
                provider_subscription_id="subs_done",
            )

            record_checkout_failed(
                user_id=buyer.id,
                plan_slug="premium_monthly",
                provider="abacatepay",
                reason="gateway down",
            )
            db.session.commit()

            funnel = summarize_funnel()

            assert funnel.started == 3
            assert funnel.completed == 1
            assert funnel.abandoned == 1
            assert funnel.failed == 1
            assert funnel.pending == 0

    def test_window_excludes_older_attempts(self, app, buyer):
        """A report for the last day must not carry last month's attempts."""
        with app.app_context():
            ancient = _start(buyer.id)
            ancient.started_at = utc_now_naive() - timedelta(days=40)
            db.session.commit()

            recent_only = summarize_funnel(since=utc_now_naive() - timedelta(days=1))

            assert recent_only.started == 0

    def test_filters_by_origin_surface(self, app, buyer):
        """Landing and in-app checkouts convert differently — that is the point."""
        with app.app_context():
            _start(buyer.id, return_surface="landing")
            _start(buyer.id, return_surface="app")
            db.session.commit()

            assert summarize_funnel(return_surface="landing").started == 1
            assert summarize_funnel(return_surface="app").started == 1
            assert summarize_funnel().started == 2

    def test_empty_window_reports_zeroes_without_dividing_by_zero(self, app):
        """A quiet day must report 0%, not raise."""
        with app.app_context():
            funnel = summarize_funnel(since=utc_now_naive() + timedelta(days=1))

            assert funnel.started == 0
            assert funnel.conversion_rate == 0.0


class TestConversionRate:
    def test_pending_attempts_are_excluded_from_the_denominator(self):
        """An undecided buyer must not drag the rate down while deciding."""
        # 1 completed, 1 abandoned, 8 still inside the window: counting the
        # pending ones as losses would report 10% instead of 50%.
        funnel = CheckoutFunnel(
            started=10, completed=1, abandoned=1, failed=0, pending=8
        )

        assert funnel.conversion_rate == 50.0

    def test_rate_is_zero_when_nothing_resolved(self):
        """Only pending attempts means no verdict yet, not a 0% conversion."""
        funnel = CheckoutFunnel(
            started=5, completed=0, abandoned=0, failed=0, pending=5
        )

        assert funnel.conversion_rate == 0.0

    def test_provider_failures_count_against_conversion(self):
        """A checkout the gateway refused is a lost sale, not a neutral event."""
        funnel = CheckoutFunnel(
            started=4, completed=2, abandoned=0, failed=2, pending=0
        )

        assert funnel.conversion_rate == 50.0


def test_attempt_repr_is_readable(app, buyer):
    """Logs and shell sessions read these directly."""
    with app.app_context():
        attempt = _start(buyer.id)

        assert "premium_monthly" in repr(attempt)
        assert CheckoutAttemptStatus.STARTED.value in repr(attempt)


def test_model_is_registered_for_migrations(app):
    """A model missing from the app factory silently never gets a table."""
    with app.app_context():
        assert CheckoutAttempt.__tablename__ in db.metadata.tables
