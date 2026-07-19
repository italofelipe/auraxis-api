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

from collections.abc import Mapping
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

ASAAS_PROVIDER = "asaas"


@runtime_checkable
class BillingWebhookParser(Protocol):
    """Structural interface for inbound webhook adapters."""

    @property
    def provider(self) -> str:
        """Canonical provider slug, as persisted on ``Subscription.provider``."""
        ...

    def verify(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        """Return whether the request is authentically from this provider.

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

    def verify(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
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


_PARSERS: dict[str, BillingWebhookParser] = {
    ASAAS_PROVIDER: AsaasWebhookParser(),
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
