"""Webhook payload parsing helpers for the subscriptions controller.

Pure functions that extract, coerce, and validate fields from raw provider
webhook payloads.  No Flask request context or database session is required.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime
from typing import Any

from flask import current_app
from flask.ctx import has_app_context

from app.config.billing_plans import resolve_checkout_plan_offer
from app.models.subscription import Subscription
from app.services.billing_adapter import BillingSubscriptionSnapshot

_WEBHOOK_SIGNATURE_HEADER = "X-Billing-Signature"
_ASAAS_WEBHOOK_TOKEN_HEADER = "asaas-access-token"
_WEBHOOK_SECRET_ENV = "BILLING_WEBHOOK_SECRET"
_WEBHOOK_ALLOW_UNSIGNED_ENV = "BILLING_WEBHOOK_ALLOW_UNSIGNED"
_ASAAS_WEBHOOK_TOKEN_ENV = "BILLING_ASAAS_WEBHOOK_TOKEN"


def _read_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _allow_unsigned_webhooks() -> bool:
    """Unsigned webhook traffic must be explicitly enabled per environment."""
    if not _read_bool_env(_WEBHOOK_ALLOW_UNSIGNED_ENV, default=False):
        return False
    if not has_app_context():
        return False
    if current_app.testing:
        return True

    runtime_env = (
        str(
            current_app.config.get("ENV")
            or current_app.config.get("FLASK_ENV")
            or current_app.config.get("APP_ENV")
            or os.getenv("FLASK_ENV")
            or os.getenv("APP_ENV")
            or os.getenv("AURAXIS_ENV")
            or ""
        )
        .strip()
        .lower()
    )
    return runtime_env in {"local", "test"}


def _verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 webhook signature.

    Default policy is fail-closed: missing ``BILLING_WEBHOOK_SECRET`` rejects
    requests unless the environment explicitly opts into unsigned webhooks.
    That keeps production strict while allowing deterministic local/test flows.
    """
    secret = os.getenv(_WEBHOOK_SECRET_ENV, "")
    if not secret:
        return _allow_unsigned_webhooks()
    if not signature:
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_asaas_webhook_token(header_value: str) -> bool:
    expected = os.getenv(_ASAAS_WEBHOOK_TOKEN_ENV, "").strip()
    if not expected:
        return False
    if not header_value.strip():
        return False
    return hmac.compare_digest(expected, header_value.strip())


def _extract_event_id(payload: dict[str, Any]) -> str | None:
    for key in ("event_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve_offer_from_external_reference(
    external_reference: str | None,
) -> dict[str, str | None]:
    raw_reference = str(external_reference or "").strip()
    if not raw_reference:
        return {
            "plan_code": None,
            "offer_code": None,
            "billing_cycle": None,
        }

    offer = resolve_checkout_plan_offer(raw_reference.split(":")[-1])
    if offer is None:
        return {
            "plan_code": None,
            "offer_code": None,
            "billing_cycle": None,
        }
    return {
        "plan_code": offer.plan_code,
        "offer_code": offer.slug,
        "billing_cycle": (offer.billing_cycle.value if offer.billing_cycle else None),
    }


def _coerce_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace("+0000", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _clean_optional_string(value: object) -> str | None:
    return str(value or "").strip() or None


def _extract_identifiers_from_subscription_object(
    subscription_object: dict[str, Any],
) -> tuple[str | None, str | None, str | None, object, object]:
    return (
        _clean_optional_string(subscription_object.get("id")),
        _clean_optional_string(subscription_object.get("customer")),
        _clean_optional_string(subscription_object.get("externalReference")),
        subscription_object.get("dateCreated"),
        subscription_object.get("nextDueDate"),
    )


def _merge_identifiers_from_payment_object(
    provider_subscription_id: str | None,
    provider_customer_id: str | None,
    external_reference: str | None,
    current_period_end: object,
    payment_object: dict[str, Any],
) -> tuple[str | None, str | None, str | None, object]:
    return (
        _clean_optional_string(payment_object.get("subscription"))
        or provider_subscription_id,
        _clean_optional_string(payment_object.get("customer")) or provider_customer_id,
        _clean_optional_string(payment_object.get("externalReference"))
        or external_reference,
        payment_object.get("dueDate") or current_period_end,
    )


def _merge_customer_from_checkout_object(
    provider_customer_id: str | None,
    checkout_object: dict[str, Any],
) -> str | None:
    return (
        _clean_optional_string(checkout_object.get("customer")) or provider_customer_id
    )


def _extract_subscription_identifiers(
    payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None, Any, Any]:
    provider_subscription_id: str | None = None
    provider_customer_id: str | None = None
    external_reference: str | None = None
    current_period_start: object | None = None
    current_period_end: object | None = None

    subscription_object = payload.get("subscription")
    payment_object = payload.get("payment")
    checkout_object = payload.get("checkout")

    if isinstance(subscription_object, dict):
        (
            provider_subscription_id,
            provider_customer_id,
            external_reference,
            current_period_start,
            current_period_end,
        ) = _extract_identifiers_from_subscription_object(subscription_object)

    if isinstance(payment_object, dict):
        (
            provider_subscription_id,
            provider_customer_id,
            external_reference,
            current_period_end,
        ) = _merge_identifiers_from_payment_object(
            provider_subscription_id,
            provider_customer_id,
            external_reference,
            current_period_end,
            payment_object,
        )

    if isinstance(checkout_object, dict):
        provider_customer_id = _merge_customer_from_checkout_object(
            provider_customer_id,
            checkout_object,
        )

    legacy_subscription_id = _clean_optional_string(payload.get("subscription_id"))
    provider_subscription_id = provider_subscription_id or legacy_subscription_id
    return (
        provider_subscription_id,
        provider_customer_id,
        external_reference,
        _coerce_datetime(current_period_start),
        _coerce_datetime(current_period_end),
    )


def _find_subscription_for_snapshot(
    snapshot: BillingSubscriptionSnapshot,
) -> Subscription | None:
    provider_subscription_id = snapshot.get("provider_id")
    if provider_subscription_id:
        subscription: Subscription | None = Subscription.query.filter_by(
            provider_subscription_id=provider_subscription_id
        ).first()
        if subscription is not None:
            return subscription

    provider_customer_id = snapshot.get("provider_customer_id")
    if provider_customer_id:
        subscription = Subscription.query.filter_by(
            provider_customer_id=provider_customer_id
        ).first()
        return subscription

    return None
