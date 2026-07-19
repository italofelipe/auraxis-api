"""Tests for the provider-agnostic billing webhook parser boundary (#1564).

The parser layer mirrors ``BillingProvider`` on the inbound side: each gateway
supplies its own signature verification, event vocabulary and payload shape,
normalised into a single ``BillingSubscriptionSnapshot``.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.controllers.billing_webhook_parsers import (
    ASAAS_PROVIDER,
    AsaasWebhookParser,
    BillingWebhookParser,
    resolve_webhook_parser,
)


class TestParserRegistry:
    def test_asaas_parser_satisfies_protocol(self) -> None:
        assert isinstance(AsaasWebhookParser(), BillingWebhookParser)

    def test_resolves_asaas_by_slug(self) -> None:
        parser = resolve_webhook_parser(ASAAS_PROVIDER)
        assert parser is not None
        assert parser.provider == ASAAS_PROVIDER

    def test_resolution_is_case_insensitive_and_trims(self) -> None:
        parser = resolve_webhook_parser("  Asaas ")
        assert parser is not None
        assert parser.provider == ASAAS_PROVIDER

    def test_defaults_to_asaas_when_unspecified(self) -> None:
        """The legacy ``/subscriptions/webhook`` route carries no provider."""
        for empty in (None, "", "   "):
            parser = resolve_webhook_parser(empty)
            assert parser is not None
            assert parser.provider == ASAAS_PROVIDER

    def test_unknown_provider_resolves_to_none(self) -> None:
        assert resolve_webhook_parser("not-a-gateway") is None


class TestAsaasEventVocabulary:
    @pytest.mark.parametrize(
        "event",
        [
            "PAYMENT_RECEIVED",
            "PAYMENT_CONFIRMED",
            "PAYMENT_OVERDUE",
            "SUBSCRIPTION_DELETED",
            "subscription.activated",
            "subscription.canceled",
            "subscription.past_due",
        ],
    )
    def test_supported_events(self, event: str) -> None:
        assert AsaasWebhookParser().supports_event(event) is True

    @pytest.mark.parametrize("event", ["", "PAYMENT_UNKNOWN", "subscription.renewed"])
    def test_unsupported_events(self, event: str) -> None:
        assert AsaasWebhookParser().supports_event(event) is False


class TestAsaasParse:
    def test_native_event_stamps_provider(self) -> None:
        snapshot = AsaasWebhookParser().parse(
            {
                "event": "PAYMENT_CONFIRMED",
                "payment": {"subscription": "sub_1", "customer": "cus_1"},
            }
        )
        assert snapshot is not None
        assert snapshot["provider"] == ASAAS_PROVIDER
        assert snapshot["status"] == "active"
        assert snapshot["provider_id"] == "sub_1"

    def test_legacy_generic_event_does_not_stamp_provider(self) -> None:
        """Legacy ``subscription.*`` events are gateway-neutral.

        Stamping them would overwrite ``Subscription.provider`` on rows that
        never came from Asaas — the behaviour the ``event_type.isupper()``
        heuristic preserved by accident.
        """
        snapshot = AsaasWebhookParser().parse(
            {"event": "subscription.activated", "subscription_id": "sub_legacy"}
        )
        assert snapshot is not None
        assert "provider" not in snapshot
        assert snapshot["status"] == "active"

    def test_unsupported_event_returns_none(self) -> None:
        assert AsaasWebhookParser().parse({"event": "PAYMENT_UNKNOWN"}) is None

    def test_payload_without_identifiers_returns_none(self) -> None:
        assert AsaasWebhookParser().parse({"event": "PAYMENT_CONFIRMED"}) is None


class TestAsaasVerify:
    def test_accepts_valid_hmac_signature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_WEBHOOK_SECRET", "s3cr3t")
        body = json.dumps({"event": "PAYMENT_CONFIRMED"}).encode()
        signature = hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()

        assert AsaasWebhookParser().verify(body, {"X-Billing-Signature": signature})

    def test_rejects_tampered_hmac_signature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_WEBHOOK_SECRET", "s3cr3t")
        monkeypatch.delenv("BILLING_ASAAS_WEBHOOK_TOKEN", raising=False)

        assert not AsaasWebhookParser().verify(b"{}", {"X-Billing-Signature": "nope"})

    def test_accepts_provider_token_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_ASAAS_WEBHOOK_TOKEN", "tok_123")

        assert AsaasWebhookParser().verify(b"{}", {"asaas-access-token": "tok_123"})

    def test_rejects_wrong_provider_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_ASAAS_WEBHOOK_TOKEN", "tok_123")
        monkeypatch.delenv("BILLING_WEBHOOK_SECRET", raising=False)

        assert not AsaasWebhookParser().verify(b"{}", {"asaas-access-token": "wrong"})


class TestProviderScopedRoute:
    """The provider-scoped route is what makes a second gateway possible."""

    def test_provider_route_accepts_asaas(self, client) -> None:  # noqa: ANN001
        resp = client.post("/subscriptions/webhook/asaas", json={"event": "noop"})
        assert resp.status_code in (200, 401)

    def test_unknown_provider_is_rejected(self, client) -> None:  # noqa: ANN001
        resp = client.post("/subscriptions/webhook/stripe", json={"event": "noop"})
        assert resp.status_code == 404

    def test_legacy_route_still_served(self, client) -> None:  # noqa: ANN001
        """Asaas is already configured against the unscoped URL in production."""
        resp = client.post("/subscriptions/webhook", json={"event": "noop"})
        assert resp.status_code in (200, 401)
