"""Tests for per-surface checkout return URLs (#1620).

The subscription checkout can start either on the product app or on the public
landing (auraxis.com.br). Whoever buys from the landing has no session on the
app domain, so sending them back there after paying would drop them on a login
screen. The provider payload therefore has to carry the return URLs of the
surface the purchase started from.

The surface is a **key into an allowlist of configured URLs** — never a URL
supplied by the client, which would be an open redirect.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.services.billing_adapter import (
    BillingCheckoutCustomer,
    resolve_checkout_return_urls,
)

APP_SUCCESS = "https://app.auraxis.com.br/checkout/success"
APP_CANCEL = "https://app.auraxis.com.br/checkout/cancel"
LANDING_SUCCESS = "https://auraxis.com.br/checkout/sucesso"
LANDING_CANCEL = "https://auraxis.com.br/checkout/cancelado"


@pytest.fixture
def _app_envs(monkeypatch) -> None:
    monkeypatch.setenv("BILLING_CHECKOUT_SUCCESS_URL", APP_SUCCESS)
    monkeypatch.setenv("BILLING_CHECKOUT_CANCEL_URL", APP_CANCEL)
    monkeypatch.delenv("BILLING_CHECKOUT_LANDING_SUCCESS_URL", raising=False)
    monkeypatch.delenv("BILLING_CHECKOUT_LANDING_CANCEL_URL", raising=False)


@pytest.fixture
def _all_envs(_app_envs, monkeypatch) -> None:
    monkeypatch.setenv("BILLING_CHECKOUT_LANDING_SUCCESS_URL", LANDING_SUCCESS)
    monkeypatch.setenv("BILLING_CHECKOUT_LANDING_CANCEL_URL", LANDING_CANCEL)


class TestResolveReturnUrls:
    def test_defaults_to_the_app_surface(self, _all_envs) -> None:
        assert resolve_checkout_return_urls(None) == (APP_SUCCESS, APP_CANCEL)

    def test_app_surface_is_explicit_too(self, _all_envs) -> None:
        assert resolve_checkout_return_urls("app") == (APP_SUCCESS, APP_CANCEL)

    def test_landing_surface_uses_landing_urls(self, _all_envs) -> None:
        assert resolve_checkout_return_urls("landing") == (
            LANDING_SUCCESS,
            LANDING_CANCEL,
        )

    def test_surface_is_case_and_space_insensitive(self, _all_envs) -> None:
        assert resolve_checkout_return_urls("  LANDING  ") == (
            LANDING_SUCCESS,
            LANDING_CANCEL,
        )

    def test_unknown_surface_falls_back_to_app(self, _all_envs) -> None:
        assert resolve_checkout_return_urls("marketing") == (APP_SUCCESS, APP_CANCEL)

    def test_landing_without_envs_falls_back_to_app(self, _app_envs) -> None:
        """Missing landing config degrades to the app URLs instead of breaking."""
        assert resolve_checkout_return_urls("landing") == (APP_SUCCESS, APP_CANCEL)

    def test_partial_landing_config_falls_back_to_app(
        self, _app_envs, monkeypatch
    ) -> None:
        monkeypatch.setenv("BILLING_CHECKOUT_LANDING_SUCCESS_URL", LANDING_SUCCESS)
        assert resolve_checkout_return_urls("landing") == (APP_SUCCESS, APP_CANCEL)

    def test_client_supplied_url_is_never_used(self, _all_envs) -> None:
        """A URL where a surface key is expected must not become a redirect."""
        success, cancel = resolve_checkout_return_urls("https://evil.example/steal")
        assert success == APP_SUCCESS
        assert cancel == APP_CANCEL

    def test_missing_app_config_returns_empty(self, monkeypatch) -> None:
        """Callers raise on empty URLs; the resolver just reports them."""
        monkeypatch.delenv("BILLING_CHECKOUT_SUCCESS_URL", raising=False)
        monkeypatch.delenv("BILLING_CHECKOUT_CANCEL_URL", raising=False)
        assert resolve_checkout_return_urls("app") == ("", "")


class TestAbacatePayUsesTheSurface:
    def _provider(self):
        from app.services.billing_adapter import AbacatePayBillingProvider

        return AbacatePayBillingProvider()

    def _customer(self) -> BillingCheckoutCustomer:
        return BillingCheckoutCustomer(
            user_id=str(uuid.uuid4()), name="QA", email="qa@test.com"
        )

    def test_landing_surface_reaches_the_provider_payload(
        self, app, _all_envs, monkeypatch
    ) -> None:
        monkeypatch.setenv("BILLING_ABACATEPAY_API_KEY", "test-key")
        monkeypatch.setenv("BILLING_ABACATEPAY_PRODUCT_PREMIUM_MONTHLY", "prod_test")
        with app.app_context():
            provider = self._provider()
            with (
                patch.object(provider, "_ensure_customer", return_value="cust_1"),
                patch.object(
                    provider,
                    "_request",
                    return_value={"url": "https://abacate/pay", "id": "bill_1"},
                ) as mock_request,
            ):
                provider.create_checkout_session(
                    customer=self._customer(),
                    plan_slug="premium_monthly",
                    return_surface="landing",
                )

            body = mock_request.call_args.kwargs["json_payload"]
            assert body["completionUrl"] == LANDING_SUCCESS
            assert body["returnUrl"] == LANDING_CANCEL

    def test_default_keeps_the_app_urls(self, app, _all_envs, monkeypatch) -> None:
        monkeypatch.setenv("BILLING_ABACATEPAY_API_KEY", "test-key")
        monkeypatch.setenv("BILLING_ABACATEPAY_PRODUCT_PREMIUM_MONTHLY", "prod_test")
        with app.app_context():
            provider = self._provider()
            with (
                patch.object(provider, "_ensure_customer", return_value="cust_1"),
                patch.object(
                    provider,
                    "_request",
                    return_value={"url": "https://abacate/pay", "id": "bill_1"},
                ) as mock_request,
            ):
                provider.create_checkout_session(
                    customer=self._customer(), plan_slug="premium_monthly"
                )

            body = mock_request.call_args.kwargs["json_payload"]
            assert body["completionUrl"] == APP_SUCCESS
            assert body["returnUrl"] == APP_CANCEL


class TestRestContract:
    """The REST endpoint forwards the surface and never trusts a URL."""

    def _login(self, client) -> dict[str, str]:
        suffix = uuid.uuid4().hex[:8]
        email = f"surface-{suffix}@test.com"
        reg = client.post(
            "/auth/register",
            json={
                "name": f"Surface {suffix}",
                "email": email,
                "password": "StrongPass@123",
            },
        )
        assert reg.status_code == 201
        login = client.post(
            "/auth/login", json={"email": email, "password": "StrongPass@123"}
        )
        assert login.status_code == 200
        return {"Authorization": f"Bearer {login.get_json()['token']}"}

    def test_surface_reaches_the_provider(self, client) -> None:
        headers = self._login(client)
        with patch(
            "app.controllers.subscription_controller._get_provider"
        ) as mock_provider:
            mock_provider.return_value.create_checkout_session.return_value = {
                "checkout_url": "https://pay/x",
                "provider": "stub",
            }
            response = client.post(
                "/subscriptions/checkout",
                json={"plan_slug": "premium_monthly", "return_surface": "landing"},
                headers=headers,
            )
        assert response.status_code in (200, 201)
        kwargs = mock_provider.return_value.create_checkout_session.call_args.kwargs
        assert kwargs["return_surface"] == "landing"

    def test_absent_surface_is_none(self, client) -> None:
        headers = self._login(client)
        with patch(
            "app.controllers.subscription_controller._get_provider"
        ) as mock_provider:
            mock_provider.return_value.create_checkout_session.return_value = {
                "checkout_url": "https://pay/x",
                "provider": "stub",
            }
            client.post(
                "/subscriptions/checkout",
                json={"plan_slug": "premium_monthly"},
                headers=headers,
            )
        kwargs = mock_provider.return_value.create_checkout_session.call_args.kwargs
        assert kwargs["return_surface"] is None

    def test_url_in_the_surface_field_is_neutralised(self, client) -> None:
        """The resolver drops it, so the app URLs are used — no open redirect."""
        headers = self._login(client)
        with patch(
            "app.controllers.subscription_controller._get_provider"
        ) as mock_provider:
            mock_provider.return_value.create_checkout_session.return_value = {
                "checkout_url": "https://pay/x",
                "provider": "stub",
            }
            client.post(
                "/subscriptions/checkout",
                json={
                    "plan_slug": "premium_monthly",
                    "return_surface": "https://evil.example/steal",
                },
                headers=headers,
            )
        kwargs = mock_provider.return_value.create_checkout_session.call_args.kwargs
        assert resolve_checkout_return_urls(kwargs["return_surface"]) == (_env_pair())


def _env_pair() -> tuple[str, str]:
    import os

    return (
        os.getenv("BILLING_CHECKOUT_SUCCESS_URL", ""),
        os.getenv("BILLING_CHECKOUT_CANCEL_URL", ""),
    )


class TestGraphqlParity:
    """REST and GraphQL must expose the same capability (repo rule)."""

    def test_mutation_accepts_the_surface_argument(self) -> None:
        from app.graphql.mutations.subscription import CreateCheckoutSessionMutation

        arguments = CreateCheckoutSessionMutation.Arguments
        assert hasattr(arguments, "return_surface")


class TestStubProviderAcceptsTheSurface:
    def test_stub_signature_matches_the_protocol(self) -> None:
        from app.services.billing_adapter import StubBillingProvider

        session = StubBillingProvider().create_checkout_session(
            customer=BillingCheckoutCustomer(
                user_id="u1", name="QA", email="qa@test.com"
            ),
            plan_slug="premium_monthly",
            return_surface="landing",
        )
        assert session["checkout_url"]
