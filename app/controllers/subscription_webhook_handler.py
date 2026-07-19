"""Webhook processing logic for the subscriptions domain.

Extracted from ``subscription_controller`` so the controller stays ≤200 LOC.
Called by the ``POST /subscriptions/webhook`` route via
``handle_webhook_request()``.

Re-exports consumed by ``billing_webhooks_cli`` remain in
``subscription_controller`` to preserve the public import surface.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast

from flask import request
from flask.typing import ResponseReturnValue

from app.application.services.billing_email_service import dispatch_billing_email
from app.controllers.billing_webhook_parsers import (
    BillingWebhookParser,
    default_webhook_parser,
)
from app.controllers.response_contract import compat_error_response
from app.controllers.subscription_webhook_payload import (
    _extract_event_id,
    _extract_subscription_identifiers,
    _find_subscription_for_snapshot,
)
from app.extensions.database import db
from app.http.request_context import current_request_id
from app.models.subscription import Subscription
from app.models.user import User
from app.models.webhook_event import WebhookEvent, WebhookEventStatus
from app.services.billing_adapter import BillingSubscriptionSnapshot
from app.services.subscription_service import apply_subscription_snapshot
from app.utils.datetime_utils import utc_now_naive
from app.utils.response_builder import json_response

logger = logging.getLogger(__name__)


def _ok(data: dict[str, Any], status: int = 200) -> ResponseReturnValue:
    return json_response({"success": True, "data": data}, status_code=status)


def _err(
    message: str,
    code: str,
    status: int,
    *,
    details: dict[str, Any] | None = None,
) -> ResponseReturnValue:
    return compat_error_response(
        legacy_payload={"success": False, "error": {"code": code, "message": message}},
        status_code=status,
        message=message,
        error_code=code,
        details=details,
    )


def _process_webhook_snapshot(
    event_type: str,
    event_id: str | None,
    snapshot: BillingSubscriptionSnapshot,
    webhook_ev: WebhookEvent,
) -> ResponseReturnValue:
    subscription: Subscription | None = _find_subscription_for_snapshot(snapshot)
    if subscription is None:
        logger.warning(
            "Webhook %s for unknown provider_subscription_id=%s — ignoring",
            event_type,
            snapshot.get("provider_id"),
        )
        webhook_ev.mark_skipped(reason="unknown_subscription")
        db.session.commit()
        return _ok({"received": True, "processed": False})

    if event_id and subscription.provider_event_id == event_id:
        webhook_ev.mark_skipped(reason="duplicate")
        db.session.commit()
        return _ok({"received": True, "processed": False, "reason": "duplicate"})

    if event_id:
        subscription.provider_event_id = event_id

    webhook_ev.mark_processed(now=utc_now_naive())
    apply_subscription_snapshot(subscription, snapshot)

    user = User.query.filter_by(id=subscription.user_id).first()
    if user is not None:
        try:
            dispatch_billing_email(
                user=user,
                subscription=subscription,
                event_type=event_type,
            )
        except Exception:
            logger.exception(
                "Failed to dispatch billing email for event=%s subscription_id=%s",
                event_type,
                str(subscription.id),
            )

    return _ok({"received": True, "processed": True})


def handle_webhook_request(
    parser: BillingWebhookParser | None = None,
) -> ResponseReturnValue:
    """Process a provider webhook POST.

    Verifies the signature, persists an audit record, and delegates to
    ``_process_webhook_snapshot`` for supported event types.  Called by
    ``subscription_controller.handle_webhook``.

    Signature scheme, event vocabulary and payload shape all come from the
    ``BillingWebhookParser`` (``app.controllers.billing_webhook_parsers``);
    unsupported events are a 200 no-op.  ``parser`` defaults to the gateway
    behind the unscoped legacy route.
    """
    if parser is None:
        parser = default_webhook_parser()

    raw_body: bytes = request.get_data()
    # Werkzeug's Headers is not a nominal Mapping, but its ``get`` is
    # case-insensitive — which is what header lookup needs.  Casting to dict
    # instead would make ``asaas-access-token`` miss ``Asaas-Access-Token``.
    headers = cast(Mapping[str, str], request.headers)
    sig_verified = parser.verify(raw_body, headers)

    payload: dict[str, Any] = request.get_json(silent=True) or {}
    event_type: str = payload.get("event", "")
    event_id = _extract_event_id(payload)

    try:
        (
            provider_subscription_id,
            provider_customer_id,
            *_,
        ) = _extract_subscription_identifiers(payload)
    except Exception:
        provider_subscription_id = None
        provider_customer_id = None

    now = utc_now_naive()
    raw_text = raw_body.decode("utf-8", errors="replace")[:50_000]
    webhook_ev = WebhookEvent(
        event_id=event_id,
        event_type=event_type or "unknown",
        provider=parser.provider,
        provider_subscription_id=provider_subscription_id,
        provider_customer_id=provider_customer_id,
        raw_payload=raw_text,
        signature_verified=sig_verified,
        received_at=now,
        status=WebhookEventStatus.RECEIVED.value,
    )
    db.session.add(webhook_ev)

    if not sig_verified:
        webhook_ev.mark_skipped(reason="invalid_signature")
        db.session.commit()
        logger.warning(
            "Billing webhook invalid signature request_id=%s",
            current_request_id(),
        )
        return _err(
            "Invalid signature",
            "UNAUTHORIZED",
            401,
            details={"request_id": current_request_id()},
        )

    if not parser.supports_event(event_type):
        webhook_ev.mark_skipped(reason=f"unsupported_event:{event_type}")
        db.session.commit()
        logger.info("Unhandled billing webhook event: %s — ignoring", event_type)
        return _ok({"received": True, "processed": False})

    snapshot = parser.parse(payload)
    if snapshot is None:
        webhook_ev.mark_skipped(reason="unresolvable_subscription")
        db.session.commit()
        return _err(
            "Unable to resolve subscription from webhook payload",
            "VALIDATION_ERROR",
            400,
        )

    try:
        return _process_webhook_snapshot(event_type, event_id, snapshot, webhook_ev)
    except Exception as exc:
        webhook_ev.mark_failed(reason=str(exc), now=utc_now_naive())
        db.session.commit()
        raise
