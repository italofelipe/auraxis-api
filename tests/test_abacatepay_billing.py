"""AbacatePay billing provider and webhook parser (#1565).

Payload fixtures are real responses captured from the AbacatePay sandbox on
2026-07-19, not hand-written guesses — the published docs contradict themselves
on the envelope, the status enum and the create response shape.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

import pytest

from app.controllers.billing_webhook_parsers import (
    ABACATEPAY_PROVIDER,
    AbacatePayWebhookParser,
    BillingWebhookParser,
    resolve_webhook_parser,
)
from app.services.billing_adapter import (
    AbacatePayBillingProvider,
    BillingCheckoutCustomer,
    BillingProviderError,
    get_default_billing_provider,
)

# Captured verbatim from POST /v2/subscriptions/create (sandbox).
CHECKOUT_RESPONSE: dict[str, Any] = {
    "success": True,
    "error": None,
    "data": {
        "id": "bill_UFJCy04PJLa2T4MMmuF6QXfz",
        "externalId": "auraxis:probe:premium_monthly",
        "url": "https://app.abacatepay.com/pay/bill_UFJCy04PJLa2T4MMmuF6QXfz",
        "amount": 2990,
        "status": "PENDING",
        "methods": ["CARD"],
        "frequency": "SUBSCRIPTION",
        "devMode": True,
        "customerId": "cust_k2AgLzqqP3PGam2s5jy5hDNq",
    },
}

CUSTOMER_RESPONSE: dict[str, Any] = {
    "success": True,
    "error": None,
    "data": {
        "id": "cust_k2AgLzqqP3PGam2s5jy5hDNq",
        "devMode": True,
        "email": "probe-min@auraxis.com.br",
        "name": "Probe Minimo",
    },
}


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = str(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    """Records requests and replays queued responses in order."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.headers: dict[str, str] = {}
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self._responses.pop(0)


@pytest.fixture
def provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_ABACATEPAY_API_KEY", "abc_dev_key")
    monkeypatch.setenv("BILLING_CHECKOUT_SUCCESS_URL", "https://auraxis.test/ok")
    monkeypatch.setenv("BILLING_CHECKOUT_CANCEL_URL", "https://auraxis.test/cancel")
    monkeypatch.setenv(
        "BILLING_ABACATEPAY_PRODUCT_PREMIUM_MONTHLY", "prod_EkfyE1e41MKuB5dMPHRmP0Jq"
    )


class TestFactory:
    def test_selects_abacatepay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BILLING_PROVIDER", "abacatepay")
        monkeypatch.setenv("BILLING_ABACATEPAY_API_KEY", "abc_dev_key")

        assert isinstance(get_default_billing_provider(), AbacatePayBillingProvider)

    def test_asaas_remains_pluggable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The migration must not delete the fallback gateway."""
        monkeypatch.setenv("BILLING_PROVIDER", "asaas")
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "asaas_key")

        assert not isinstance(get_default_billing_provider(), AbacatePayBillingProvider)


class TestCheckout:
    def test_creates_checkout_and_returns_hosted_url(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = AbacatePayBillingProvider()
        session = _FakeSession(
            [_FakeResponse(CUSTOMER_RESPONSE), _FakeResponse(CHECKOUT_RESPONSE)]
        )
        monkeypatch.setattr(provider, "_session", session)

        result = provider.create_checkout_session(
            BillingCheckoutCustomer(
                user_id="user-1", name="Ana", email="ana@auraxis.test"
            ),
            "premium_monthly",
        )

        assert result["checkout_url"] == (
            "https://app.abacatepay.com/pay/bill_UFJCy04PJLa2T4MMmuF6QXfz"
        )
        assert result["provider"] == ABACATEPAY_PROVIDER
        assert result["provider_customer_id"] == "cust_k2AgLzqqP3PGam2s5jy5hDNq"
        # The bill id is a placeholder until the webhook delivers the subs id.
        assert result["provider_subscription_id"] == "bill_UFJCy04PJLa2T4MMmuF6QXfz"

    def test_sends_product_id_not_price(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Price and cycle live on the product, never in the request."""
        provider = AbacatePayBillingProvider()
        session = _FakeSession(
            [_FakeResponse(CUSTOMER_RESPONSE), _FakeResponse(CHECKOUT_RESPONSE)]
        )
        monkeypatch.setattr(provider, "_session", session)

        provider.create_checkout_session(
            BillingCheckoutCustomer("user-1", "Ana", "ana@auraxis.test"),
            "premium_monthly",
        )

        body = session.calls[-1]["json"]
        assert body["items"] == [{"id": "prod_EkfyE1e41MKuB5dMPHRmP0Jq", "quantity": 1}]
        assert "price" not in body
        assert body["metadata"]["user_id"] == "user-1"

    def test_missing_product_mapping_is_explicit(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BILLING_ABACATEPAY_PRODUCT_PREMIUM_MONTHLY")
        provider = AbacatePayBillingProvider()
        monkeypatch.setattr(provider, "_session", _FakeSession([]))

        with pytest.raises(BillingProviderError, match="PRODUCT_PREMIUM_MONTHLY"):
            provider.create_checkout_session(
                BillingCheckoutCustomer("user-1", "Ana", "ana@auraxis.test"),
                "premium_monthly",
            )

    def test_customer_failure_degrades_to_anonymous_checkout(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Losing the customer record must not lose the sale."""
        provider = AbacatePayBillingProvider()
        session = _FakeSession(
            [
                _FakeResponse({"success": False, "error": "Invalid taxId"}, 400),
                _FakeResponse(CHECKOUT_RESPONSE),
            ]
        )
        monkeypatch.setattr(provider, "_session", session)

        result = provider.create_checkout_session(
            BillingCheckoutCustomer("user-1", "Ana", "ana@auraxis.test"),
            "premium_monthly",
        )

        assert result["checkout_url"].startswith("https://app.abacatepay.com/pay/")
        assert "customerId" not in session.calls[-1]["json"]

    def test_business_error_raises(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """success:false with HTTP 400 is the real error shape."""
        provider = AbacatePayBillingProvider()
        session = _FakeSession(
            [
                _FakeResponse(CUSTOMER_RESPONSE),
                _FakeResponse(
                    {
                        "success": False,
                        "data": None,
                        "error": "PIX Automático is not available for this store",
                    },
                    400,
                ),
            ]
        )
        monkeypatch.setattr(provider, "_session", session)

        with pytest.raises(BillingProviderError, match="PIX Automático"):
            provider.create_checkout_session(
                BillingCheckoutCustomer("user-1", "Ana", "ana@auraxis.test"),
                "premium_monthly",
            )


class TestSubscriptionQueries:
    def test_get_subscription_maps_undocumented_active_status(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ACTIVE is absent from the declared enum but is what the API returns."""
        provider = AbacatePayBillingProvider()
        monkeypatch.setattr(
            provider,
            "_session",
            _FakeSession(
                [
                    _FakeResponse(
                        {
                            "success": True,
                            "error": None,
                            "data": {
                                "id": "subs_1",
                                "status": "ACTIVE",
                                "customerId": "cust_1",
                            },
                        }
                    )
                ]
            ),
        )

        snapshot = provider.get_subscription("subs_1")

        assert snapshot["status"] == "active"
        assert snapshot["provider_id"] == "subs_1"

    def test_unknown_status_degrades_instead_of_raising(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = AbacatePayBillingProvider()
        monkeypatch.setattr(
            provider,
            "_session",
            _FakeSession(
                [
                    _FakeResponse(
                        {
                            "success": True,
                            "error": None,
                            "data": {"id": "subs_1", "status": "SOMETHING_NEW"},
                        }
                    )
                ]
            ),
        )

        assert provider.get_subscription("subs_1")["status"] == "past_due"

    def test_unpaid_checkout_does_not_hit_the_api(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stored bill_ id means the customer has not paid yet.

        Querying it returns 400 "Subscription not found", which would 500
        GET /subscriptions/me for everyone mid-checkout.
        """
        provider = AbacatePayBillingProvider()
        session = _FakeSession([])  # any request would raise IndexError
        monkeypatch.setattr(provider, "_session", session)

        snapshot = provider.get_subscription("bill_UFJCy04PJLa2T4MMmuF6QXfz")

        assert session.calls == []
        assert "status" not in snapshot
        assert snapshot["provider_id"] == "bill_UFJCy04PJLa2T4MMmuF6QXfz"

    def test_no_status_leaves_subscription_untouched(self) -> None:
        """The placeholder snapshot must be a no-op when applied."""
        from app.services.subscription_service import _set_if_changed

        current = "active"
        result, changed = _set_if_changed(current, None)

        assert result == current
        assert changed is False

    def test_cancel_subscription(
        self, provider_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = AbacatePayBillingProvider()
        session = _FakeSession(
            [
                _FakeResponse(
                    {
                        "success": True,
                        "error": None,
                        "data": {"id": "subs_1", "status": "CANCELLED"},
                    }
                )
            ]
        )
        monkeypatch.setattr(provider, "_session", session)

        assert provider.cancel_subscription("subs_1")["status"] == "canceled"
        assert session.calls[0]["json"] == {"id": "subs_1"}


def _webhook(event: str, *, dev_mode: bool = False) -> dict[str, Any]:
    return {
        "id": "log_abc123",
        "event": event,
        "apiVersion": 2,
        "devMode": dev_mode,
        "data": {
            "subscription": {
                "id": "subs_tAFqDWBhcEYTjQh2K0ZYDHau",
                "status": "ACTIVE",
                "frequency": "MONTHLY",
                "updatedAt": "2024-12-06T20:00:05.000Z",
            },
            "customer": {"id": "cust_def456", "email": "maria@exemplo.com"},
            "checkout": {"id": "bill_jskd3TMfScHZDJe5NSZjTmQ4"},
        },
    }


class TestWebhookParser:
    def test_registered_and_satisfies_protocol(self) -> None:
        parser = resolve_webhook_parser("abacatepay")
        assert parser is not None
        assert isinstance(parser, BillingWebhookParser)

    @pytest.mark.parametrize(
        ("event", "expected"),
        [
            ("subscription.trial_started", "trialing"),
            ("subscription.completed", "active"),
            ("subscription.renewed", "active"),
            ("subscription.cancelled", "canceled"),
            ("subscription.payment_failed", "past_due"),
        ],
    )
    def test_event_status_mapping(self, event: str, expected: str) -> None:
        snapshot = AbacatePayWebhookParser().parse(_webhook(event))
        assert snapshot is not None
        assert snapshot["status"] == expected

    def test_promotes_bill_placeholder_to_subscription_id(self) -> None:
        snapshot = AbacatePayWebhookParser().parse(_webhook("subscription.completed"))
        assert snapshot is not None
        assert snapshot["provider_id"] == "subs_tAFqDWBhcEYTjQh2K0ZYDHau"
        assert snapshot["provider_customer_id"] == "cust_def456"
        assert snapshot["provider"] == ABACATEPAY_PROVIDER

    def test_trial_started_carries_trial_end_date(self) -> None:
        """trial_ends_at feeds trial_expiry_cli and the D-N reminders."""
        payload = _webhook("subscription.trial_started")
        payload["data"]["subscription"]["trialEndsAt"] = "2026-07-26T23:59:59.999Z"

        snapshot = AbacatePayWebhookParser().parse(payload)

        assert snapshot is not None
        assert snapshot["status"] == "trialing"
        trial_ends_at = snapshot["trial_ends_at"]
        assert trial_ends_at is not None
        assert trial_ends_at.date().isoformat() == "2026-07-26"

    def test_renewal_without_trial_data_omits_trial_end(self) -> None:
        """A renewal must not wipe the date recorded when the trial started."""
        snapshot = AbacatePayWebhookParser().parse(_webhook("subscription.renewed"))

        assert snapshot is not None
        assert "trial_ends_at" not in snapshot

    def test_ignores_unknown_event(self) -> None:
        assert AbacatePayWebhookParser().parse(_webhook("checkout.refunded")) is None

    def test_sandbox_traffic_rejected_in_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """devMode events must never move real subscriptions."""
        monkeypatch.setenv("APP_ENV", "production")
        payload = _webhook("subscription.completed", dev_mode=True)

        assert AbacatePayWebhookParser().parse(payload) is None

    def test_devmode_escape_hatch_is_off_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absent config must reject — the opt-in has to be deliberate."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("BILLING_ABACATEPAY_ALLOW_DEVMODE", raising=False)

        payload = _webhook("subscription.completed", dev_mode=True)
        assert AbacatePayWebhookParser().parse(payload) is None

    @pytest.mark.parametrize("flag", ["false", "0", "no", "off", "", "maybe"])
    def test_devmode_escape_hatch_rejects_non_truthy_values(
        self, monkeypatch: pytest.MonkeyPatch, flag: str
    ) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("BILLING_ABACATEPAY_ALLOW_DEVMODE", flag)

        payload = _webhook("subscription.completed", dev_mode=True)
        assert AbacatePayWebhookParser().parse(payload) is None

    def test_devmode_accepted_in_production_when_explicitly_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("BILLING_ABACATEPAY_ALLOW_DEVMODE", "true")

        payload = _webhook("subscription.completed", dev_mode=True)
        assert AbacatePayWebhookParser().parse(payload) is not None

    def test_sandbox_traffic_accepted_outside_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("APP_ENV", "local")
        payload = _webhook("subscription.completed", dev_mode=True)

        assert AbacatePayWebhookParser().parse(payload) is not None


class TestWebhookVerification:
    def test_rejects_when_secret_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("BILLING_ABACATEPAY_WEBHOOK_SECRET", raising=False)

        assert not AbacatePayWebhookParser().verify(b"{}", {}, {"webhookSecret": "x"})

    def test_accepts_platform_env_secret_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ABACATE_PAY_WEBHOOK_SECRET is the name the secret ships under."""
        monkeypatch.delenv("BILLING_ABACATEPAY_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("ABACATE_PAY_WEBHOOK_SECRET", "from_platform_env")
        monkeypatch.delenv("BILLING_ABACATEPAY_SIGNING_KEY", raising=False)

        parser = AbacatePayWebhookParser()
        assert parser.verify(b"{}", {}, {"webhookSecret": "from_platform_env"})
        assert not parser.verify(b"{}", {}, {"webhookSecret": "wrong"})

    def test_accepts_matching_query_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_ABACATEPAY_WEBHOOK_SECRET", "s3cr3t")
        monkeypatch.delenv("BILLING_ABACATEPAY_SIGNING_KEY", raising=False)

        assert AbacatePayWebhookParser().verify(b"{}", {}, {"webhookSecret": "s3cr3t"})

    def test_rejects_wrong_query_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BILLING_ABACATEPAY_WEBHOOK_SECRET", "s3cr3t")

        assert not AbacatePayWebhookParser().verify(
            b"{}", {}, {"webhookSecret": "wrong"}
        )

    def test_rejects_missing_query_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_ABACATEPAY_WEBHOOK_SECRET", "s3cr3t")

        assert not AbacatePayWebhookParser().verify(b"{}", {}, None)

    def test_signature_checked_when_signing_key_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_ABACATEPAY_WEBHOOK_SECRET", "s3cr3t")
        monkeypatch.setenv("BILLING_ABACATEPAY_SIGNING_KEY", "pubkey")
        body = b'{"event":"subscription.renewed"}'
        digest = hmac.new(b"pubkey", body, hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode()
        parser = AbacatePayWebhookParser()

        assert parser.verify(
            body, {"X-Webhook-Signature": signature}, {"webhookSecret": "s3cr3t"}
        )
        assert not parser.verify(
            body, {"X-Webhook-Signature": "bogus"}, {"webhookSecret": "s3cr3t"}
        )
