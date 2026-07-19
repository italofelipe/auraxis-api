"""Subscriptions controller — J9 (billing / plan management).

Exposes five endpoints:
  GET  /subscriptions/plans    — public billing plan catalog        (public)
  GET  /subscriptions/me       — current user subscription state (auth required)
  POST /subscriptions/checkout — create a checkout session      (auth required)
  POST /subscriptions/cancel   — cancel the subscription        (auth required)
  POST /subscriptions/webhook  — provider webhook               (no auth)

Webhook processing logic lives in ``subscription_webhook_handler``.
Serialisation helpers live in ``app.schemas.openapi.subscription.response``.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from flask import Blueprint, current_app, request
from flask.typing import ResponseReturnValue

from app.auth import get_active_auth_context, get_active_user
from app.config.billing_plans import (
    list_public_billing_plans,
    resolve_checkout_plan_offer,
)
from app.controllers.billing_webhook_parsers import (
    resolve_webhook_parser as resolve_webhook_parser,  # re-export for CLI
)
from app.controllers.response_contract import compat_error_response
from app.controllers.subscription_webhook_handler import (
    _process_webhook_snapshot as _process_webhook_snapshot,  # noqa: F401  re-export
)
from app.controllers.subscription_webhook_handler import (
    handle_webhook_request,
)
from app.controllers.subscription_webhook_payload import (
    _extract_event_id as _extract_event_id,  # re-export for billing_webhooks_cli
)
from app.extensions.database import db
from app.models.subscription import Subscription, SubscriptionStatus
from app.schemas.openapi.subscription.response import serialize_subscription
from app.services.billing_adapter import (
    BillingCheckoutCustomer,
    BillingProvider,
    BillingProviderError,
    get_default_billing_provider,
)
from app.services.subscription_service import (
    cancel_subscription,
    get_or_create_subscription,
    sync_subscription_from_provider,
)
from app.utils.response_builder import json_response

logger = logging.getLogger(__name__)

subscription_bp = Blueprint("subscriptions", __name__, url_prefix="/subscriptions")


def _get_provider() -> BillingProvider:
    return get_default_billing_provider()


_CHECKOUT_SESSION_FAILURE_MESSAGE = "Failed to create checkout session"


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


# ---------------------------------------------------------------------------
# GET /subscriptions/plans
# ---------------------------------------------------------------------------


@subscription_bp.get("/plans")
def list_subscription_plans() -> ResponseReturnValue:
    """Return the public billing plan catalog for MVP1."""
    return _ok({"plans": list_public_billing_plans()})


# ---------------------------------------------------------------------------
# GET /subscriptions/me
# ---------------------------------------------------------------------------


@subscription_bp.get("/me")
def get_my_subscription() -> ResponseReturnValue:
    """Return the authenticated user's current subscription state."""
    auth = get_active_auth_context()
    sub = get_or_create_subscription(UUID(auth.subject))
    provider = _get_provider()
    sub = sync_subscription_from_provider(sub, provider)
    return _ok({"subscription": serialize_subscription(sub)})


# ---------------------------------------------------------------------------
# POST /subscriptions/checkout
# ---------------------------------------------------------------------------


@subscription_bp.post("/checkout")
def create_checkout_session() -> ResponseReturnValue:
    """Create a billing checkout session for the requested plan."""
    auth, user = get_active_user()

    body: dict[str, Any] = request.get_json(silent=True) or {}
    plan_slug: str | None = body.get("plan_slug")
    if not plan_slug:
        return _err("plan_slug is required", "VALIDATION_ERROR", 400)

    billing_cycle_raw: str | None = (
        str(body.get("billing_cycle") or "").strip().lower() or None
    )
    if billing_cycle_raw:
        offer = resolve_checkout_plan_offer(
            f"{plan_slug}_{billing_cycle_raw}"
        ) or resolve_checkout_plan_offer(plan_slug)
    else:
        offer = resolve_checkout_plan_offer(plan_slug)

    if offer is None:
        return _err("Unsupported plan_slug", "VALIDATION_ERROR", 400)

    provider = _get_provider()
    try:
        result = provider.create_checkout_session(
            customer=BillingCheckoutCustomer(
                user_id=str(UUID(auth.subject)),
                name=str(user.name),
                email=str(user.email),
            ),
            plan_slug=offer.slug,
        )
    except BillingProviderError:
        current_app.logger.exception(_CHECKOUT_SESSION_FAILURE_MESSAGE)
        return _err(_CHECKOUT_SESSION_FAILURE_MESSAGE, "UPSTREAM_ERROR", 502)
    except Exception:
        current_app.logger.exception(_CHECKOUT_SESSION_FAILURE_MESSAGE)
        return _err(_CHECKOUT_SESSION_FAILURE_MESSAGE, "INTERNAL_ERROR", 500)

    subscription = get_or_create_subscription(UUID(auth.subject))
    provider_name = str(result.get("provider") or "").strip()
    provider_customer_id = result.get("provider_customer_id")
    if provider_name:
        subscription.provider = provider_name
    if isinstance(provider_customer_id, str) and provider_customer_id.strip():
        subscription.provider_customer_id = provider_customer_id.strip()
    db.session.commit()

    return _ok(
        {
            "plan_slug": offer.slug,
            "plan_code": offer.plan_code,
            "billing_cycle": (
                offer.billing_cycle.value if offer.billing_cycle else None
            ),
            "checkout_url": result.get("checkout_url"),
            "provider": result.get("provider"),
        },
        201,
    )


# ---------------------------------------------------------------------------
# POST /subscriptions/cancel
# ---------------------------------------------------------------------------


@subscription_bp.post("/cancel")
def cancel_my_subscription() -> ResponseReturnValue:
    """Cancel the authenticated user's subscription."""
    auth = get_active_auth_context()

    sub: Subscription = get_or_create_subscription(UUID(auth.subject))
    if sub.status == SubscriptionStatus.CANCELED:
        return _err("Subscription is already canceled", "ALREADY_CANCELED", 409)

    provider = _get_provider()
    try:
        sub = cancel_subscription(sub, provider)
    except Exception:
        current_app.logger.exception("Failed to cancel subscription")
        return _err("Failed to cancel subscription", "INTERNAL_ERROR", 500)

    return _ok({"subscription": serialize_subscription(sub)})


# ---------------------------------------------------------------------------
# POST /subscriptions/webhook
# ---------------------------------------------------------------------------


@subscription_bp.post("/webhook")
def handle_webhook() -> ResponseReturnValue:
    """Receive webhook events for the default gateway.

    Kept unscoped for retrocompatibility: this URL is already registered in the
    Asaas dashboard in production.  New gateways use the scoped route below.
    """
    return handle_webhook_request()


@subscription_bp.post("/webhook/<provider>")
def handle_provider_webhook(provider: str) -> ResponseReturnValue:
    """Receive webhook events for an explicitly named gateway.

    Routing by path segment keeps each provider's signature scheme and event
    vocabulary isolated, instead of guessing the origin from payload shape.
    """
    parser = resolve_webhook_parser(provider)
    if parser is None:
        return _err(
            f"Unknown billing provider: {provider}",
            "NOT_FOUND",
            404,
        )
    return handle_webhook_request(parser)


def register_subscription_dependencies(app: Any) -> None:  # noqa: ANN401
    """No-op dependency registration kept for symmetry with other controllers."""
