"""Provider-agnostic inbound boundary for billing webhooks (#1564).

``BillingProvider`` (``app.services.billing_adapter``) makes the *outbound* side
of billing pluggable.  This module is its inbound counterpart: each gateway
brings its own signature scheme, event vocabulary and payload envelope, and
normalises them into a single ``BillingSubscriptionSnapshot``.

Adding a gateway means adding a parser and registering it — not editing a
shared event map.  A flat map shared across gateways is genuinely ambiguous:
different providers reuse the same event names with different meanings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.controllers.subscription_webhook_payload import (
    _ASAAS_WEBHOOK_TOKEN_HEADER,
    _WEBHOOK_SIGNATURE_HEADER,
    _extract_subscription_identifiers,
    _resolve_offer_from_external_reference,
    _verify_asaas_webhook_token,
    _verify_webhook_signature,
)
from app.models.subscription import SubscriptionStatus
from app.services.billing_adapter import BillingSubscriptionSnapshot

logger = logging.getLogger(__name__)

ASAAS_PROVIDER = "asaas"
ABACATEPAY_PROVIDER = "abacatepay"

_ABACATEPAY_SIGNATURE_HEADER = "X-Webhook-Signature"
_ABACATEPAY_SECRET_QUERY_PARAM = "webhookSecret"
_ABACATEPAY_WEBHOOK_SECRET_ENV = "BILLING_ABACATEPAY_WEBHOOK_SECRET"
# Name the secret ships under in the platform .env.
_ABACATEPAY_WEBHOOK_SECRET_FALLBACK_ENV = "ABACATE_PAY_WEBHOOK_SECRET"
_ABACATEPAY_SIGNING_KEY_ENV = "BILLING_ABACATEPAY_SIGNING_KEY"
_ABACATEPAY_ALLOW_DEVMODE_ENV = "BILLING_ABACATEPAY_ALLOW_DEVMODE"

_PRODUCTION_ENV_NAMES = {"prod", "production"}
_TRUTHY = {"1", "true", "yes", "on"}


def _is_production_runtime() -> bool:
    for var in ("FLASK_ENV", "APP_ENV", "AURAXIS_ENV"):
        value = str(os.getenv(var) or "").strip().lower()
        if value:
            return value in _PRODUCTION_ENV_NAMES
    return False


def _devmode_allowed_in_production() -> bool:
    """Escape hatch for validating a sandbox key against the production API.

    Off by default and meant to be temporary: while it is on, sandbox traffic
    can move real subscriptions.  Turn it off as soon as the paid-path check
    is done.
    """
    return (
        str(os.getenv(_ABACATEPAY_ALLOW_DEVMODE_ENV) or "").strip().lower() in _TRUTHY
    )


def _abacatepay_webhook_secret() -> str:
    return (
        os.getenv(_ABACATEPAY_WEBHOOK_SECRET_ENV, "").strip()
        or os.getenv(_ABACATEPAY_WEBHOOK_SECRET_FALLBACK_ENV, "").strip()
    )


def _clean(value: object) -> str | None:
    return str(value or "").strip() or None


def _coerce_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


@runtime_checkable
class BillingWebhookParser(Protocol):
    """Structural interface for inbound webhook adapters."""

    @property
    def provider(self) -> str:
        """Canonical provider slug, as persisted on ``Subscription.provider``."""
        ...

    def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
    ) -> bool:
        """Return whether the request is authentically from this provider.

        ``query`` carries the request query string: not every gateway puts its
        shared secret in a header (AbacatePay sends it as ``?webhookSecret=``).
        Implementations must be fail-closed: absent configuration rejects.
        """
        ...

    def supports_event(self, event_type: str) -> bool:
        """Return whether this event type maps to a subscription state change."""
        ...

    def parse(self, payload: dict[str, Any]) -> BillingSubscriptionSnapshot | None:
        """Normalise a payload, or return ``None`` when it is not actionable."""
        ...


def _build_snapshot(
    payload: dict[str, Any],
    *,
    status: str,
    provider: str | None,
) -> BillingSubscriptionSnapshot | None:
    """Assemble a snapshot from provider-neutral identifier extraction."""
    (
        provider_subscription_id,
        provider_customer_id,
        external_reference,
        current_period_start,
        current_period_end,
    ) = _extract_subscription_identifiers(payload)

    if not provider_customer_id and not provider_subscription_id:
        return None

    offer_metadata = _resolve_offer_from_external_reference(external_reference)
    snapshot: BillingSubscriptionSnapshot = {
        "status": status,
        "provider_customer_id": provider_customer_id,
        "current_period_start": current_period_start,
        "current_period_end": current_period_end,
    }
    if provider:
        snapshot["provider"] = provider
    if provider_subscription_id:
        snapshot["provider_id"] = provider_subscription_id
    if offer_metadata["plan_code"]:
        snapshot["plan_code"] = offer_metadata["plan_code"]
    if offer_metadata["offer_code"]:
        snapshot["offer_code"] = offer_metadata["offer_code"]
    if offer_metadata["billing_cycle"]:
        snapshot["billing_cycle"] = offer_metadata["billing_cycle"]
    return snapshot


class AsaasWebhookParser:
    """Asaas webhooks, plus the gateway-neutral legacy ``subscription.*`` events.

    The two vocabularies are kept in separate maps on purpose.  Only the
    Asaas-native events stamp ``provider`` on the snapshot; the legacy generic
    events are gateway-neutral and must not overwrite ``Subscription.provider``
    on rows that never came from Asaas.  That distinction was previously an
    ``event_type.isupper()`` heuristic — correct by accident, and silently
    wrong the moment a second gateway used uppercase event names.
    """

    _NATIVE_EVENTS = {
        "PAYMENT_RECEIVED": SubscriptionStatus.ACTIVE.value,
        "PAYMENT_CONFIRMED": SubscriptionStatus.ACTIVE.value,
        "PAYMENT_OVERDUE": SubscriptionStatus.PAST_DUE.value,
        "SUBSCRIPTION_DELETED": SubscriptionStatus.CANCELED.value,
    }
    _LEGACY_EVENTS = {
        "subscription.activated": SubscriptionStatus.ACTIVE.value,
        "subscription.canceled": SubscriptionStatus.CANCELED.value,
        "subscription.past_due": SubscriptionStatus.PAST_DUE.value,
    }

    @property
    def provider(self) -> str:
        return ASAAS_PROVIDER

    def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
    ) -> bool:
        del query  # Asaas authenticates via headers only.
        signature = headers.get(_WEBHOOK_SIGNATURE_HEADER, "")
        token = headers.get(_ASAAS_WEBHOOK_TOKEN_HEADER, "")
        return _verify_webhook_signature(raw_body, signature) or (
            _verify_asaas_webhook_token(token)
        )

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._NATIVE_EVENTS or event_type in self._LEGACY_EVENTS

    def parse(self, payload: dict[str, Any]) -> BillingSubscriptionSnapshot | None:
        event_type = str(payload.get("event") or "").strip()

        status = self._NATIVE_EVENTS.get(event_type)
        if status is not None:
            return _build_snapshot(payload, status=status, provider=ASAAS_PROVIDER)

        legacy_status = self._LEGACY_EVENTS.get(event_type)
        if legacy_status is not None:
            return _build_snapshot(payload, status=legacy_status, provider=None)

        return None


def _resolve_abacatepay_customer_id(data: dict[str, Any]) -> str | None:
    """Find the customer id, which moves between payload variants.

    The automatic-cancellation payload (max retries exceeded) ships without the
    ``checkout`` block, and anonymous checkouts ship without ``customer``.
    """
    customer_object = data.get("customer")
    if isinstance(customer_object, dict):
        customer_id = _clean(customer_object.get("id"))
        if customer_id:
            return customer_id

    checkout_object = data.get("checkout")
    if isinstance(checkout_object, dict):
        return _clean(checkout_object.get("customerId"))
    return None


def _resolve_abacatepay_external_reference(data: dict[str, Any]) -> str | None:
    """Find the ``auraxis:{user_id}:{offer_slug}`` reference we sent at checkout.

    It surfaces in different sub-objects depending on the event, so probe all
    three.  Without it the snapshot carries no plan, ``plan_code`` stays Free,
    and a paid subscription lands active with Free entitlements.
    """
    for key in ("checkout", "payment", "subscription"):
        obj = data.get(key)
        if isinstance(obj, dict):
            reference = _clean(obj.get("externalId")) or _clean(
                obj.get("externalReference")
            )
            if reference:
                return reference
    return None


def _build_abacatepay_snapshot(
    data: dict[str, Any],
    subscription_object: dict[str, Any],
    *,
    status: str,
    provider_subscription_id: str | None,
    provider_customer_id: str | None,
) -> BillingSubscriptionSnapshot:
    snapshot: BillingSubscriptionSnapshot = {
        "status": status,
        "provider": ABACATEPAY_PROVIDER,
        "provider_customer_id": provider_customer_id,
        "current_period_start": _coerce_datetime(subscription_object.get("updatedAt")),
        "current_period_end": _coerce_datetime(subscription_object.get("nextChargeAt")),
    }

    offer_metadata = _resolve_offer_from_external_reference(
        _resolve_abacatepay_external_reference(data)
    )
    if offer_metadata["plan_code"]:
        # Entitlements derive from plan_code — without this a paid sub stays on
        # Free features despite an active status.
        snapshot["plan_code"] = offer_metadata["plan_code"]
    if offer_metadata["offer_code"]:
        snapshot["offer_code"] = offer_metadata["offer_code"]
    if offer_metadata["billing_cycle"]:
        snapshot["billing_cycle"] = offer_metadata["billing_cycle"]

    trial_ends_at = _coerce_datetime(subscription_object.get("trialEndsAt"))
    if trial_ends_at is not None:
        # Drives trial_expiry_cli and the D-N ending reminders.
        snapshot["trial_ends_at"] = trial_ends_at

    if provider_subscription_id:
        # Promotes the stored bill_… placeholder to the real subs_… id.
        snapshot["provider_id"] = provider_subscription_id
    return snapshot


class AbacatePayWebhookParser:
    """AbacatePay webhooks (API v2 envelope).

    Authenticity rests on two independent layers, both required when
    configured:

    1. ``?webhookSecret=`` query param — the value we registered with the
       gateway.  This is the *real* barrier.
    2. HMAC-SHA256 (base64) over the raw body in ``X-Webhook-Signature``.
       AbacatePay signs with a key published in its own documentation and
       shared across all merchants, so this proves the payload shape was not
       mangled — it does NOT prove origin.  Defence in depth only.

    Because layer 2 is not a real secret, layer 1 is mandatory: a missing or
    mismatched ``webhookSecret`` rejects regardless of the signature.
    """

    _EVENTS = {
        "subscription.trial_started": SubscriptionStatus.TRIALING.value,
        "subscription.completed": SubscriptionStatus.ACTIVE.value,
        "subscription.renewed": SubscriptionStatus.ACTIVE.value,
        "subscription.cancelled": SubscriptionStatus.CANCELED.value,
        "subscription.payment_failed": SubscriptionStatus.PAST_DUE.value,
    }

    @property
    def provider(self) -> str:
        return ABACATEPAY_PROVIDER

    def verify(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
        query: Mapping[str, str] | None = None,
    ) -> bool:
        expected_secret = _abacatepay_webhook_secret()
        if not expected_secret:
            return False

        received_secret = str((query or {}).get(_ABACATEPAY_SECRET_QUERY_PARAM) or "")
        if not hmac.compare_digest(expected_secret, received_secret.strip()):
            return False

        signing_key = os.getenv(_ABACATEPAY_SIGNING_KEY_ENV, "").strip()
        if not signing_key:
            # Signature checking is opt-in: the gateway's key is public, so
            # requiring it would add friction without adding authenticity.
            return True

        signature = headers.get(_ABACATEPAY_SIGNATURE_HEADER, "").strip()
        if not signature:
            return False
        digest = hmac.new(signing_key.encode(), raw_body, hashlib.sha256).digest()
        return hmac.compare_digest(base64.b64encode(digest).decode(), signature)

    def supports_event(self, event_type: str) -> bool:
        return event_type in self._EVENTS

    def _devmode_blocks(self, payload: dict[str, Any]) -> bool:
        """Whether a sandbox payload must be dropped in this runtime."""
        if not (payload.get("devMode") is True and _is_production_runtime()):
            return False
        if not _devmode_allowed_in_production():
            return True
        logger.warning(
            "Accepting AbacatePay devMode webhook in production because "
            "%s is enabled — turn it off once validation is done",
            _ABACATEPAY_ALLOW_DEVMODE_ENV,
        )
        return False

    def parse(self, payload: dict[str, Any]) -> BillingSubscriptionSnapshot | None:
        event_type = str(payload.get("event") or "").strip()
        status = self._EVENTS.get(event_type)
        if status is None or self._devmode_blocks(payload):
            return None

        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        subscription_object = data.get("subscription")
        if not isinstance(subscription_object, dict):
            return None

        provider_subscription_id = _clean(subscription_object.get("id"))
        provider_customer_id = _resolve_abacatepay_customer_id(data)
        if not provider_subscription_id and not provider_customer_id:
            return None

        return _build_abacatepay_snapshot(
            data,
            subscription_object,
            status=status,
            provider_subscription_id=provider_subscription_id,
            provider_customer_id=provider_customer_id,
        )


_PARSERS: dict[str, BillingWebhookParser] = {
    ASAAS_PROVIDER: AsaasWebhookParser(),
    ABACATEPAY_PROVIDER: AbacatePayWebhookParser(),
}

_DEFAULT_PROVIDER = ASAAS_PROVIDER


def resolve_webhook_parser(provider: str | None) -> BillingWebhookParser | None:
    """Return the parser for ``provider``, or ``None`` when unknown.

    An empty provider resolves to the default gateway so the unscoped
    ``POST /subscriptions/webhook`` route — already registered in the Asaas
    dashboard in production — keeps working unchanged.
    """
    slug = str(provider or "").strip().lower() or _DEFAULT_PROVIDER
    return _PARSERS.get(slug)


def default_webhook_parser() -> BillingWebhookParser:
    """Parser backing the unscoped legacy ``POST /subscriptions/webhook`` route."""
    return _PARSERS[_DEFAULT_PROVIDER]


def registered_providers() -> tuple[str, ...]:
    """Provider slugs accepted by the provider-scoped webhook route."""
    return tuple(sorted(_PARSERS))
