"""Tests for the ``flask billing-webhooks retry-failed`` CLI (#1556).

Covers:
- Reprocessing a FAILED event back to PROCESSED (with billing email dispatch)
- Idempotency: duplicate provider_event_id is skipped on retry
- max-retries cap keeps exhausted events out of the eligible set
- Backlog alert: logger.error + Sentry capture when FAILED events accumulate
- No alert when the backlog is below the threshold
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from app.extensions.database import db
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.models.webhook_event import WebhookEvent, WebhookEventStatus
from app.services.email_provider import get_email_outbox
from app.utils.datetime_utils import utc_now_naive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_with_subscription(
    *, customer_id: str, provider_subscription_id: str | None = None
) -> Subscription:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        name=f"Webhook {suffix}",
        email=f"webhook-{suffix}@test.com",
        password="hash",
    )
    db.session.add(user)
    db.session.flush()
    subscription = Subscription(
        user_id=user.id,
        plan_code="premium",
        status=SubscriptionStatus.PAST_DUE,
        provider="asaas",
        provider_customer_id=customer_id,
        provider_subscription_id=provider_subscription_id,
    )
    db.session.add(subscription)
    db.session.commit()
    return subscription


def _make_failed_event(
    *,
    event_id: str,
    customer_id: str,
    raw_payload: str | None = None,
    retry_count: int = 0,
    event_type: str = "PAYMENT_CONFIRMED",
) -> WebhookEvent:
    payload = raw_payload
    if payload is None:
        payload = json.dumps(
            {
                "event": event_type,
                "id": event_id,
                "payment": {"customer": customer_id, "dueDate": "2030-01-01"},
            }
        )
    event = WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider="asaas",
        provider_customer_id=customer_id,
        raw_payload=payload,
        signature_verified=True,
        status=WebhookEventStatus.FAILED.value,
        failure_reason="boom",
        retry_count=retry_count,
        received_at=utc_now_naive() - timedelta(hours=1),
    )
    db.session.add(event)
    db.session.commit()
    return event


# ---------------------------------------------------------------------------
# Reprocessing
# ---------------------------------------------------------------------------


def test_retry_failed_reprocesses_event_to_processed(app) -> None:
    with app.app_context():
        subscription = _make_user_with_subscription(customer_id="cus_retry_1")
        event = _make_failed_event(event_id="evt_retry_1", customer_id="cus_retry_1")
        event_pk = event.id
        subscription_pk = subscription.id

        runner = app.test_cli_runner()
        result = runner.invoke(args=["billing-webhooks", "retry-failed"])

        assert result.exit_code == 0
        assert "processed=1" in result.output

        refreshed = db.session.get(WebhookEvent, event_pk)
        assert refreshed is not None
        assert refreshed.status == WebhookEventStatus.PROCESSED.value

        sub = db.session.get(Subscription, subscription_pk)
        assert sub is not None
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.provider_event_id == "evt_retry_1"

        outbox = get_email_outbox()
        assert any(entry["tag"] == "billing_payment_confirmed" for entry in outbox)
        outbox.clear()


def test_retry_failed_skips_duplicate_provider_event_id(app) -> None:
    """Events whose provider_event_id was already applied must be skipped."""
    with app.app_context():
        subscription = _make_user_with_subscription(customer_id="cus_dup_1")
        subscription.provider_event_id = "evt_dup_1"
        db.session.commit()
        event = _make_failed_event(event_id="evt_dup_1", customer_id="cus_dup_1")
        event_pk = event.id

        runner = app.test_cli_runner()
        result = runner.invoke(args=["billing-webhooks", "retry-failed"])

        assert result.exit_code == 0
        refreshed = db.session.get(WebhookEvent, event_pk)
        assert refreshed is not None
        assert refreshed.status == WebhookEventStatus.SKIPPED.value
        assert len(get_email_outbox()) == 0


def test_retry_failed_respects_max_retries(app) -> None:
    with app.app_context():
        _make_user_with_subscription(customer_id="cus_max_1")
        event = _make_failed_event(
            event_id="evt_max_1", customer_id="cus_max_1", retry_count=3
        )
        event_pk = event.id

        runner = app.test_cli_runner()
        result = runner.invoke(args=["billing-webhooks", "retry-failed"])

        assert result.exit_code == 0
        assert "no eligible events" in result.output
        refreshed = db.session.get(WebhookEvent, event_pk)
        assert refreshed is not None
        assert refreshed.status == WebhookEventStatus.FAILED.value


# ---------------------------------------------------------------------------
# Backlog alerting
# ---------------------------------------------------------------------------


def test_retry_failed_alerts_on_accumulated_backlog(app, monkeypatch) -> None:
    """FAILED events left after the run must trigger a Sentry alert."""
    import sentry_sdk

    captured: list[tuple[str, str | None]] = []

    def _fake_capture_message(message: str, level: str | None = None, **_: object):
        captured.append((message, level))
        return None

    monkeypatch.setattr(sentry_sdk, "capture_message", _fake_capture_message)

    with app.app_context():
        _make_user_with_subscription(customer_id="cus_alert_1")
        # Exhausted event: stays FAILED and is not eligible for retry.
        _make_failed_event(
            event_id="evt_alert_1", customer_id="cus_alert_1", retry_count=3
        )

        runner = app.test_cli_runner()
        result = runner.invoke(args=["billing-webhooks", "retry-failed"])

        assert result.exit_code == 0
        assert "backlog=1" in result.output
        assert len(captured) == 1
        message, level = captured[0]
        assert "FAILED" in message
        assert "1" in message
        assert level == "error"


def test_retry_failed_alert_counts_events_failing_again(app, monkeypatch) -> None:
    """An event that fails again during retry still counts toward the backlog."""
    import sentry_sdk

    captured: list[str] = []
    monkeypatch.setattr(
        sentry_sdk,
        "capture_message",
        lambda message, level=None, **_: captured.append(message),
    )

    with app.app_context():
        _make_failed_event(
            event_id="evt_bad_1",
            customer_id="cus_bad_1",
            raw_payload="not-json{{",
        )

        runner = app.test_cli_runner()
        result = runner.invoke(args=["billing-webhooks", "retry-failed"])

        assert result.exit_code == 0
        assert "failed=1" in result.output
        assert "backlog=1" in result.output
        assert len(captured) == 1


def test_retry_failed_no_alert_below_threshold(app, monkeypatch) -> None:
    import sentry_sdk

    captured: list[str] = []
    monkeypatch.setattr(
        sentry_sdk,
        "capture_message",
        lambda message, level=None, **_: captured.append(message),
    )

    with app.app_context():
        subscription = _make_user_with_subscription(customer_id="cus_clean_1")
        _make_failed_event(event_id="evt_clean_1", customer_id="cus_clean_1")
        assert subscription is not None

        runner = app.test_cli_runner()
        result = runner.invoke(args=["billing-webhooks", "retry-failed"])

        assert result.exit_code == 0
        assert "processed=1" in result.output
        # Everything was reprocessed — no backlog, no alert.
        assert captured == []
        get_email_outbox().clear()


def test_retry_failed_alert_threshold_option_raises_bar(app, monkeypatch) -> None:
    import sentry_sdk

    captured: list[str] = []
    monkeypatch.setattr(
        sentry_sdk,
        "capture_message",
        lambda message, level=None, **_: captured.append(message),
    )

    with app.app_context():
        _make_failed_event(
            event_id="evt_thresh_1",
            customer_id="cus_thresh_1",
            retry_count=3,
        )

        runner = app.test_cli_runner()
        result = runner.invoke(
            args=["billing-webhooks", "retry-failed", "--alert-threshold", "5"]
        )

        assert result.exit_code == 0
        # Backlog (1) below threshold (5): no Sentry alert.
        assert captured == []
