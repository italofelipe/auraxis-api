"""Flask CLI commands for billing webhook operational management (PAY-03)."""

from __future__ import annotations

import logging
from typing import Any

import click
from flask import Flask

logger = logging.getLogger(__name__)


def _retry_single_event(event: Any) -> tuple[bool, str | None]:
    """Process one failed webhook event. Returns (processed, error_message)."""
    import json as _json

    from app.controllers.subscription_controller import (
        _extract_event_id,
        _process_webhook_snapshot,
        resolve_webhook_parser,
    )
    from app.extensions.database import db
    from app.utils.datetime_utils import utc_now_naive

    if not event.raw_payload:
        event.mark_failed(reason="missing_raw_payload", now=utc_now_naive())
        db.session.commit()
        return False, "missing_raw_payload"

    try:
        payload: dict[str, Any] = _json.loads(event.raw_payload)
    except Exception as exc:
        event.mark_failed(reason=f"payload_parse_error:{exc}", now=utc_now_naive())
        db.session.commit()
        return False, f"payload_parse_error:{exc}"

    # Reprocess with the parser of the gateway that originally sent the event,
    # not whichever provider happens to be active now.
    parser = resolve_webhook_parser(getattr(event, "provider", None))
    if parser is None:
        event.mark_failed(
            reason=f"unknown_provider:{event.provider}", now=utc_now_naive()
        )
        db.session.commit()
        return False, f"unknown_provider:{event.provider}"

    snapshot = parser.parse(payload)
    if snapshot is None:
        event.mark_failed(
            reason="unresolvable_subscription_on_retry", now=utc_now_naive()
        )
        db.session.commit()
        return False, "unresolvable_subscription_on_retry"

    event_type: str = payload.get("event", "")
    event_id = _extract_event_id(payload)

    try:
        _process_webhook_snapshot(event_type, event_id, snapshot, event)
        return True, None
    except Exception as exc:
        event.mark_failed(reason=str(exc), now=utc_now_naive())
        db.session.commit()
        logger.exception(
            "billing-webhooks retry-failed: error reprocessing event id=%s",
            event.id,
        )
        return False, str(exc)


def _alert_failed_backlog(threshold: int) -> int:
    """Alert (log + Sentry) when FAILED webhook events accumulate (#1556).

    Counts every event still in FAILED status — including those that
    exhausted ``--max-retries`` and need manual intervention.  Returns the
    backlog size so callers can report it.
    """
    from sqlalchemy import func

    from app.extensions.database import db
    from app.models.webhook_event import WebhookEvent, WebhookEventStatus

    backlog = (
        db.session.query(func.count(WebhookEvent.id))
        .filter(WebhookEvent.status == WebhookEventStatus.FAILED.value)
        .scalar()
        or 0
    )
    if backlog < threshold:
        return int(backlog)

    oldest = (
        db.session.query(func.min(WebhookEvent.received_at))
        .filter(WebhookEvent.status == WebhookEventStatus.FAILED.value)
        .scalar()
    )
    logger.error(
        "billing-webhooks: %d webhook event(s) stuck in FAILED status "
        "(threshold=%d oldest_received_at=%s) — manual review required",
        backlog,
        threshold,
        oldest,
    )
    try:
        import sentry_sdk

        sentry_sdk.capture_message(
            f"billing-webhooks: {backlog} webhook event(s) stuck in FAILED "
            f"status (threshold={threshold}, oldest_received_at={oldest})",
            level="error",
        )
    except Exception:
        logger.debug(
            "Sentry unavailable for billing-webhooks backlog alert", exc_info=True
        )
    return int(backlog)


def register_billing_webhooks_commands(app: Flask) -> None:
    @app.cli.group("billing-webhooks")
    def billing_webhooks_group() -> None:
        """Operational commands for billing webhook events."""

    @billing_webhooks_group.command("retry-failed")
    @click.option(
        "--max-events",
        default=50,
        show_default=True,
        type=int,
        help="Maximum number of failed events to retry in a single run.",
    )
    @click.option(
        "--max-retries",
        default=3,
        show_default=True,
        type=int,
        help="Skip events that have already been retried this many times.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Log eligible events without reprocessing them.",
    )
    @click.option(
        "--alert-threshold",
        default=1,
        show_default=True,
        type=int,
        help=(
            "Emit a Sentry/log alert when at least this many events remain "
            "in FAILED status after the run."
        ),
    )
    def retry_failed(
        max_events: int, max_retries: int, dry_run: bool, alert_threshold: int
    ) -> None:
        """Retry webhook events that failed during processing.

        Reprocesses up to ``--max-events`` events whose status is ``failed``
        and whose ``retry_count`` is below ``--max-retries``.  Each successful
        retry updates the event status to ``processed``; each new failure
        increments ``retry_count`` and keeps status ``failed``.  After the
        run, any remaining FAILED backlog above ``--alert-threshold`` is
        reported via log + Sentry (#1556).
        """
        from app.extensions.database import db
        from app.models.webhook_event import WebhookEvent, WebhookEventStatus

        eligible = (
            db.session.query(WebhookEvent)
            .filter(
                WebhookEvent.status == WebhookEventStatus.FAILED.value,
                WebhookEvent.retry_count < max_retries,
            )
            .order_by(WebhookEvent.received_at.asc())
            .limit(max_events)
            .all()
        )

        if not eligible:
            click.echo("billing-webhooks retry-failed: no eligible events found.")
            backlog = _alert_failed_backlog(alert_threshold)
            click.echo(
                f"billing-webhooks retry-failed: backlog={backlog} "
                "FAILED event(s) remaining."
            )
            return

        click.echo(
            f"billing-webhooks retry-failed: {len(eligible)} event(s) eligible "
            f"(dry_run={dry_run})."
        )

        processed_count = 0
        failed_count = 0

        for event in eligible:
            click.echo(
                f"  event id={event.id} event_type={event.event_type!r} "
                f"retry_count={event.retry_count}"
            )
            if dry_run:
                continue
            processed, error = _retry_single_event(event)
            if processed:
                processed_count += 1
                click.echo("    → processed")
            else:
                failed_count += 1
                click.echo(f"    → failed: {error}")

        click.echo(
            f"billing-webhooks retry-failed: done — "
            f"processed={processed_count} failed={failed_count} "
            f"skipped_dry_run={len(eligible) if dry_run else 0}"
        )
        backlog = _alert_failed_backlog(alert_threshold)
        click.echo(
            f"billing-webhooks retry-failed: backlog={backlog} "
            "FAILED event(s) remaining."
        )
