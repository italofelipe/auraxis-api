"""Tests for J9 — billing provider adapter and subscription state endpoints."""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime
from typing import Dict
from unittest.mock import MagicMock

from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User
from app.services.billing_adapter import (
    AsaasBillingProvider,
    BillingCheckoutCustomer,
    BillingProvider,
    BillingProviderError,
    StubBillingProvider,
    get_default_billing_provider,
)
from app.services.subscription_service import (
    cancel_subscription,
    get_or_create_subscription,
    sync_subscription_from_provider,
)

# ---------------------------------------------------------------------------
# Helpers shared by controller tests
# ---------------------------------------------------------------------------


def _register_and_login(client, *, prefix: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    email = f"{prefix}-{suffix}@email.com"
    password = "StrongPass@123"

    r = client.post(
        "/auth/register",
        json={"name": f"user-{suffix}", "email": email, "password": password},
    )
    assert r.status_code == 201

    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return r.get_json()["token"]


def _auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# StubBillingProvider unit tests
# ---------------------------------------------------------------------------


class TestStubBillingProvider:
    def setup_method(self) -> None:
        self.provider = StubBillingProvider()

    def test_implements_protocol(self) -> None:
        assert isinstance(self.provider, BillingProvider)

    def test_get_subscription_returns_active_status(self) -> None:
        result = self.provider.get_subscription("sub_123")
        assert result["status"] == "active"
        assert result["provider_id"] == "sub_123"
        assert result["provider"] == "stub"

    def test_cancel_subscription_returns_canceled_status(self) -> None:
        result = self.provider.cancel_subscription("sub_123")
        assert result["status"] == "canceled"
        assert result["provider"] == "stub"

    def test_create_checkout_session_returns_url(self) -> None:
        result = self.provider.create_checkout_session(
            BillingCheckoutCustomer(
                user_id="user_abc",
                name="Auraxis User",
                email="user_abc@email.com",
            ),
            "premium_monthly",
        )
        assert "checkout_url" in result
        assert "premium_monthly" in result["checkout_url"]
        assert result["provider"] == "stub"


class TestBillingProviderFactory:
    def test_factory_returns_stub_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv("BILLING_PROVIDER", raising=False)
        provider = get_default_billing_provider()
        assert isinstance(provider, StubBillingProvider)

    def test_factory_returns_asaas_when_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("BILLING_PROVIDER", "asaas")
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "asaas_test_key")
        provider = get_default_billing_provider()
        assert isinstance(provider, AsaasBillingProvider)


class TestAsaasBillingProvider:
    def test_create_checkout_session_returns_customer_id_and_url(
        self, monkeypatch
    ) -> None:
        provider = AsaasBillingProvider()
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "asaas_test_key")
        monkeypatch.setenv(
            "BILLING_CHECKOUT_SUCCESS_URL", "https://auraxis.com/success"
        )
        monkeypatch.setenv("BILLING_CHECKOUT_CANCEL_URL", "https://auraxis.com/cancel")
        responses = iter(
            [
                {"id": "cus_123"},
                {"id": "chk_123", "link": "https://asaas.com/c/chk_123"},
            ]
        )

        def _fake_request(
            method: str, path: str, *, json_payload: object | None = None
        ):
            payload = next(responses)
            assert method == "POST"
            if path == "/customers":
                assert json_payload is not None
            return payload

        monkeypatch.setattr(provider, "_request", _fake_request)

        result = provider.create_checkout_session(
            BillingCheckoutCustomer(
                user_id="user_123",
                name="Auraxis User",
                email="user_123@email.com",
            ),
            "premium_monthly",
        )

        assert result["provider"] == "asaas"
        assert result["provider_customer_id"] == "cus_123"
        assert result["checkout_url"] == "https://asaas.com/c/chk_123"

    def test_create_checkout_session_requires_callback_urls(self, monkeypatch) -> None:
        provider = AsaasBillingProvider()
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "asaas_test_key")
        monkeypatch.delenv("BILLING_CHECKOUT_SUCCESS_URL", raising=False)
        monkeypatch.delenv("BILLING_CHECKOUT_CANCEL_URL", raising=False)

        monkeypatch.setattr(provider, "_ensure_customer", lambda _customer: "cus_123")

        try:
            provider.create_checkout_session(
                BillingCheckoutCustomer(
                    user_id="user_123",
                    name="Auraxis User",
                    email="user_123@email.com",
                ),
                "premium_monthly",
            )
        except BillingProviderError as exc:
            assert "BILLING_CHECKOUT_SUCCESS_URL" in str(exc)
        else:
            raise AssertionError("Expected BillingProviderError")

    def test_get_subscription_maps_external_reference(self, monkeypatch) -> None:
        provider = AsaasBillingProvider()
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "asaas_test_key")

        def _fake_request(
            method: str, path: str, *, json_payload: object | None = None
        ):
            assert method == "GET"
            assert path == "/subscriptions/sub_123"
            assert json_payload is None
            return {
                "id": "sub_123",
                "customer": "cus_123",
                "status": "ACTIVE",
                "cycle": "MONTHLY",
                "externalReference": "auraxis:user_123:premium_monthly",
                "dateCreated": "2026-03-29T00:00:00+00:00",
                "nextDueDate": "2026-04-29",
            }

        monkeypatch.setattr(provider, "_request", _fake_request)

        snapshot = provider.get_subscription("sub_123")
        assert snapshot["provider"] == "asaas"
        assert snapshot["provider_id"] == "sub_123"
        assert snapshot["provider_customer_id"] == "cus_123"
        assert snapshot["plan_code"] == "premium"
        assert snapshot["offer_code"] == "premium_monthly"
        assert snapshot["billing_cycle"] == "monthly"

    def test_cancel_subscription_maps_provider_payload(self, monkeypatch) -> None:
        provider = AsaasBillingProvider()
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "asaas_test_key")

        def _fake_request(
            method: str, path: str, *, json_payload: object | None = None
        ):
            assert method == "DELETE"
            assert path == "/subscriptions/sub_123"
            assert json_payload is None
            return {"id": "sub_123", "customer": "cus_123"}

        monkeypatch.setattr(provider, "_request", _fake_request)

        snapshot = provider.cancel_subscription("sub_123")
        assert snapshot["provider"] == "asaas"
        assert snapshot["provider_id"] == "sub_123"
        assert snapshot["provider_customer_id"] == "cus_123"
        assert snapshot["status"] == "canceled"


# ---------------------------------------------------------------------------
# Subscription service unit tests
# ---------------------------------------------------------------------------


class TestSubscriptionService:
    def test_get_or_create_creates_free_subscription(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            sub = get_or_create_subscription(user_id)
            assert sub.user_id == user_id
            assert sub.plan_code == "free"
            assert sub.status == SubscriptionStatus.FREE

    def test_get_or_create_returns_existing_subscription(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            sub1 = get_or_create_subscription(user_id)
            sub2 = get_or_create_subscription(user_id)
            assert sub1.id == sub2.id

    def test_sync_skips_when_no_provider_id(self, app) -> None:
        user_id = uuid.uuid4()
        provider = StubBillingProvider()
        with app.app_context():
            sub = get_or_create_subscription(user_id)
            assert sub.provider_subscription_id is None
            synced = sync_subscription_from_provider(sub, provider)
            # Status unchanged — no provider ID means nothing to sync
            assert synced.status == SubscriptionStatus.FREE

    def test_sync_updates_status_from_provider(self, app) -> None:
        user_id = uuid.uuid4()
        mock_provider = MagicMock()
        mock_provider.get_subscription.return_value = {
            "status": "active",
            "plan_code": "premium",
            "offer_code": "premium_monthly",
            "billing_cycle": "monthly",
        }
        with app.app_context():
            from app.extensions.database import db

            sub = get_or_create_subscription(user_id)
            sub.provider_subscription_id = "sub_xyz"
            db.session.commit()

            synced = sync_subscription_from_provider(sub, mock_provider)
            assert synced.status == SubscriptionStatus.ACTIVE
            assert synced.plan_code == "premium"
            assert synced.billing_cycle == BillingCycle.MONTHLY
            mock_provider.get_subscription.assert_called_once_with("sub_xyz")

    def test_sync_updates_entitlements_version_on_status_change(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            from app.extensions.database import db

            user = User(
                id=user_id,
                name="Auraxis User",
                email="auraxis-user@email.com",
                password="hash",
            )
            db.session.add(user)
            db.session.commit()

            sub = get_or_create_subscription(user_id)
            sub.provider_subscription_id = "sub_xyz"
            db.session.commit()

            provider = MagicMock()
            provider.get_subscription.return_value = {
                "status": "active",
                "plan_code": "premium",
                "offer_code": "premium_monthly",
                "billing_cycle": "monthly",
                "current_period_end": datetime.fromisoformat("2026-12-31T00:00:00"),
            }

            synced = sync_subscription_from_provider(sub, provider)
            db.session.refresh(user)

            assert synced.status == SubscriptionStatus.ACTIVE
            assert user.entitlements_version == 1

    def test_cancel_sets_canceled_status(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            sub = get_or_create_subscription(user_id)
            provider = StubBillingProvider()
            canceled = cancel_subscription(sub, provider)
            assert canceled.status == SubscriptionStatus.CANCELED

    def test_cancel_calls_provider_when_provider_id_present(self, app) -> None:
        user_id = uuid.uuid4()
        mock_provider = MagicMock()
        mock_provider.cancel_subscription.return_value = {"status": "canceled"}
        with app.app_context():
            from app.extensions.database import db

            sub = get_or_create_subscription(user_id)
            sub.provider_subscription_id = "sub_abc"
            db.session.commit()

            cancel_subscription(sub, mock_provider)
            mock_provider.cancel_subscription.assert_called_once_with("sub_abc")

    def test_cancel_updates_entitlements_version_for_real_user(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            from app.extensions.database import db

            user = User(
                id=user_id,
                name="Auraxis User",
                email="cancel-user@email.com",
                password="hash",
            )
            db.session.add(user)
            db.session.commit()

            sub = get_or_create_subscription(user_id)
            sub.status = SubscriptionStatus.ACTIVE
            sub.plan_code = "premium"
            sub.billing_cycle = BillingCycle.MONTHLY
            sub.provider = "stub"
            sub.provider_subscription_id = "sub_abc"
            db.session.commit()

            canceled = cancel_subscription(sub, StubBillingProvider())
            db.session.refresh(user)

            assert canceled.status == SubscriptionStatus.CANCELED
            assert user.entitlements_version == 1


# ---------------------------------------------------------------------------
# Subscription controller endpoint tests
# ---------------------------------------------------------------------------


class TestGetMySubscription:
    def test_get_plans_returns_public_catalog(self, client) -> None:
        resp = client.get("/subscriptions/plans")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        plans = body["data"]["plans"]
        assert len(plans) == 3
        assert plans[0]["slug"] == "free"
        assert plans[1]["slug"] == "premium_monthly"
        assert plans[2]["slug"] == "premium_annual"

    def test_get_subscription_new_user_returns_free(self, client) -> None:
        """GET /subscriptions/me — new users start on Free (#1569).

        The 7-day trial now lives on the gateway product and requires a card,
        so it is granted by webhook rather than at registration.
        """
        token = _register_and_login(client, prefix="sub-get")
        resp = client.get("/subscriptions/me", headers=_auth_headers(token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        sub = body["data"]["subscription"]
        assert sub["plan_code"] == "free"
        assert sub["status"] == "free"
        assert sub["trial_ends_at"] is None

    def test_get_subscription_returns_401_without_token(self, client) -> None:
        resp = client.get("/subscriptions/me")
        assert resp.status_code == 401

    def test_get_subscription_active_returns_data(self, client, app) -> None:
        """GET /subscriptions/me when subscription exists — returns correct data."""
        token = _register_and_login(client, prefix="sub-active")

        # Trigger record creation first
        resp0 = client.get("/subscriptions/me", headers=_auth_headers(token))
        assert resp0.status_code == 200
        sub_id = resp0.get_json()["data"]["subscription"]["id"]

        # Patch status directly in the DB
        with app.app_context():
            from app.extensions.database import db

            sub: Subscription = Subscription.query.filter_by(
                id=uuid.UUID(sub_id)
            ).first()  # type: ignore[assignment]
            sub.status = SubscriptionStatus.ACTIVE
            sub.plan_code = "premium"
            sub.billing_cycle = BillingCycle.MONTHLY
            db.session.commit()

        resp = client.get("/subscriptions/me", headers=_auth_headers(token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["subscription"]["status"] == "active"
        assert body["data"]["subscription"]["plan_code"] == "premium"
        assert body["data"]["subscription"]["offer_code"] == "premium_monthly"
        assert body["data"]["subscription"]["billing_cycle"] == "monthly"


class TestCreateCheckoutSession:
    def test_checkout_returns_checkout_url(self, client) -> None:
        token = _register_and_login(client, prefix="sub-checkout")
        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "premium_monthly"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["success"] is True
        assert "checkout_url" in body["data"]
        assert body["data"]["plan_slug"] == "premium_monthly"
        assert body["data"]["plan_code"] == "premium"
        assert body["data"]["billing_cycle"] == "monthly"
        assert "premium_monthly" in body["data"]["checkout_url"]

    def test_checkout_legacy_alias_is_normalized(self, client) -> None:
        token = _register_and_login(client, prefix="sub-checkout-legacy")
        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "pro_monthly"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["data"]["plan_slug"] == "premium_monthly"

    def test_checkout_unknown_plan_slug_returns_400(self, client) -> None:
        token = _register_and_login(client, prefix="sub-checkout-unknown")
        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "invalid-plan"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_checkout_missing_plan_slug_returns_400(self, client) -> None:
        token = _register_and_login(client, prefix="sub-checkout-err")
        resp = client.post(
            "/subscriptions/checkout",
            json={},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["success"] is False
        assert body["error"]["code"] == "VALIDATION_ERROR"

    def test_checkout_requires_auth(self, client) -> None:
        resp = client.post("/subscriptions/checkout", json={"plan_slug": "pro_monthly"})
        assert resp.status_code == 401

    def test_checkout_plan_code_plus_billing_cycle_resolves_monthly(
        self, client
    ) -> None:
        """plan_slug='pro' + billing_cycle='monthly' must resolve premium_monthly."""
        token = _register_and_login(client, prefix="sub-checkout-cycle-m")
        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "pro", "billing_cycle": "monthly"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["success"] is True
        assert body["data"]["plan_slug"] == "premium_monthly"
        assert body["data"]["billing_cycle"] == "monthly"

    def test_checkout_plan_code_plus_billing_cycle_resolves_annual(
        self, client
    ) -> None:
        """plan_slug='pro' + billing_cycle='annual' must resolve premium_annual."""
        token = _register_and_login(client, prefix="sub-checkout-cycle-a")
        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "pro", "billing_cycle": "annual"},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["success"] is True
        assert body["data"]["plan_slug"] == "premium_annual"
        assert body["data"]["billing_cycle"] == "annual"

    def test_checkout_persists_provider_customer_id(
        self, client, app, monkeypatch
    ) -> None:
        token = _register_and_login(client, prefix="sub-checkout-provider")

        class _FakeProvider:
            def create_checkout_session(
                self, customer: BillingCheckoutCustomer, plan_slug: str
            ) -> dict[str, str]:
                assert customer.email.endswith("@email.com")
                assert plan_slug == "premium_monthly"
                return {
                    "checkout_url": "https://asaas.com/c/chk_123",
                    "provider": "asaas",
                    "provider_customer_id": "cus_123",
                }

        monkeypatch.setattr(
            "app.controllers.subscription_controller._get_provider",
            lambda: _FakeProvider(),
        )

        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "premium_monthly"},
            headers=_auth_headers(token),
        )

        assert resp.status_code == 201
        with app.app_context():
            sub = Subscription.query.filter_by(provider_customer_id="cus_123").first()
            assert sub is not None
            assert sub.provider == "asaas"


class TestCancelSubscription:
    def test_cancel_sets_status_canceled(self, client) -> None:
        token = _register_and_login(client, prefix="sub-cancel")
        # Ensure subscription exists first
        client.get("/subscriptions/me", headers=_auth_headers(token))

        resp = client.post("/subscriptions/cancel", headers=_auth_headers(token))
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["data"]["subscription"]["status"] == "canceled"

    def test_cancel_already_canceled_returns_409(self, client) -> None:
        token = _register_and_login(client, prefix="sub-cancel2")
        client.get("/subscriptions/me", headers=_auth_headers(token))
        # First cancel
        client.post("/subscriptions/cancel", headers=_auth_headers(token))
        # Second cancel
        resp = client.post("/subscriptions/cancel", headers=_auth_headers(token))
        assert resp.status_code == 409

    def test_cancel_requires_auth(self, client) -> None:
        resp = client.post("/subscriptions/cancel")
        assert resp.status_code == 401


class TestWebhook:
    def test_unknown_event_returns_200_noop(self, client) -> None:
        resp = client.post(
            "/subscriptions/webhook",
            json={"event": "unknown.event", "subscription_id": "sub_xyz"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert body["data"]["received"] is True
        assert body["data"]["processed"] is False

    def test_empty_payload_returns_200_noop(self, client) -> None:
        resp = client.post("/subscriptions/webhook", json={})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["processed"] is False

    def test_webhook_no_auth_header_accepted(self, client) -> None:
        """Webhook must NOT require JWT — providers call it without tokens."""
        resp = client.post(
            "/subscriptions/webhook",
            json={"event": "unknown.event.no_auth_check"},
        )
        assert resp.status_code == 200

    def test_webhook_known_event_unknown_subscription_returns_200(self, client) -> None:
        resp = client.post(
            "/subscriptions/webhook",
            json={
                "event": "subscription.activated",
                "subscription_id": "nonexistent_sub",
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["processed"] is False

    def test_webhook_updates_subscription_status(self, client, app) -> None:
        token = _register_and_login(client, prefix="sub-wh")
        # Ensure subscription exists and capture its ID
        r = client.get("/subscriptions/me", headers=_auth_headers(token))
        sub_id = r.get_json()["data"]["subscription"]["id"]

        with app.app_context():
            from app.extensions.database import db

            sub: Subscription = Subscription.query.filter_by(
                id=uuid.UUID(sub_id)
            ).first()  # type: ignore[assignment]
            sub.provider_subscription_id = "sub_webhook_test"
            db.session.commit()

        resp = client.post(
            "/subscriptions/webhook",
            json={
                "event": "subscription.canceled",
                "subscription_id": "sub_webhook_test",
                "event_id": "evt_001",
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["processed"] is True

        with app.app_context():
            sub_updated: Subscription = Subscription.query.filter_by(
                id=uuid.UUID(sub_id)
            ).first()  # type: ignore[assignment]
            assert sub_updated.status == SubscriptionStatus.CANCELED
            assert sub_updated.provider_event_id == "evt_001"

    def test_webhook_idempotency_skips_duplicate_event(self, client, app) -> None:
        token = _register_and_login(client, prefix="sub-wh-idem")
        r = client.get("/subscriptions/me", headers=_auth_headers(token))
        sub_id = r.get_json()["data"]["subscription"]["id"]

        with app.app_context():
            from app.extensions.database import db

            sub: Subscription = Subscription.query.filter_by(
                id=uuid.UUID(sub_id)
            ).first()  # type: ignore[assignment]
            sub.provider_subscription_id = "sub_idem"
            sub.provider_event_id = "evt_already_seen"
            db.session.commit()

        resp = client.post(
            "/subscriptions/webhook",
            json={
                "event": "subscription.canceled",
                "subscription_id": "sub_idem",
                "event_id": "evt_already_seen",
            },
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"].get("reason") == "duplicate"
        assert body["data"]["processed"] is False

    def test_webhook_rejects_unsigned_requests_when_explicitly_hardened(
        self,
        client,
        monkeypatch,
    ) -> None:
        monkeypatch.delenv("BILLING_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("BILLING_WEBHOOK_ALLOW_UNSIGNED", "false")

        resp = client.post(
            "/subscriptions/webhook",
            json={"event": "unknown.event", "subscription_id": "sub_xyz"},
        )

        assert resp.status_code == 401
        body = resp.get_json()
        assert body["success"] is False
        assert body["error"]["code"] == "UNAUTHORIZED"

    def test_webhook_rejects_unsigned_requests_outside_local_or_test_env(
        self,
        client,
        monkeypatch,
    ) -> None:
        monkeypatch.delenv("BILLING_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("BILLING_WEBHOOK_ALLOW_UNSIGNED", "true")
        monkeypatch.setenv("APP_ENV", "dev")

        original_testing = client.application.testing
        client.application.testing = False
        try:
            resp = client.post(
                "/subscriptions/webhook",
                json={"event": "unknown.event", "subscription_id": "sub_xyz"},
            )
        finally:
            client.application.testing = original_testing

        assert resp.status_code == 401
        body = resp.get_json()
        assert body["success"] is False
        assert body["error"]["code"] == "UNAUTHORIZED"

    def test_webhook_accepts_valid_signature_when_secret_is_configured(
        self,
        client,
        monkeypatch,
    ) -> None:
        secret = "billing-webhook-secret"
        monkeypatch.setenv("BILLING_WEBHOOK_SECRET", secret)
        monkeypatch.setenv("BILLING_WEBHOOK_ALLOW_UNSIGNED", "false")

        raw_body = b'{"event":"unknown.event","subscription_id":"sub_xyz"}'
        signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

        resp = client.post(
            "/subscriptions/webhook",
            data=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Billing-Signature": signature,
            },
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["received"] is True
        assert body["data"]["processed"] is False

    def test_webhook_accepts_valid_asaas_token(self, client, monkeypatch) -> None:
        monkeypatch.delenv("BILLING_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("BILLING_WEBHOOK_ALLOW_UNSIGNED", "false")
        monkeypatch.setenv("BILLING_ASAAS_WEBHOOK_TOKEN", "asaas-webhook-token")

        resp = client.post(
            "/subscriptions/webhook",
            json={"event": "unknown.event", "subscription_id": "sub_xyz"},
            headers={"asaas-access-token": "asaas-webhook-token"},
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["processed"] is False

    def test_asaas_payment_webhook_updates_subscription_by_customer_id(
        self,
        client,
        app,
        monkeypatch,
    ) -> None:
        monkeypatch.delenv("BILLING_WEBHOOK_SECRET", raising=False)
        monkeypatch.setenv("BILLING_WEBHOOK_ALLOW_UNSIGNED", "false")
        monkeypatch.setenv("BILLING_ASAAS_WEBHOOK_TOKEN", "asaas-webhook-token")

        token = _register_and_login(client, prefix="sub-wh-asaas")
        response = client.get("/subscriptions/me", headers=_auth_headers(token))
        sub_id = response.get_json()["data"]["subscription"]["id"]

        with app.app_context():
            from app.extensions.database import db

            sub = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert sub is not None
            sub.provider_customer_id = "cus_asaas_123"
            db.session.commit()
            user = User.query.filter_by(id=sub.user_id).first()
            assert user is not None
            user_id = str(sub.user_id)

        resp = client.post(
            "/subscriptions/webhook",
            json={
                "id": "evt_asaas_123",
                "event": "PAYMENT_RECEIVED",
                "payment": {
                    "customer": "cus_asaas_123",
                    "subscription": "sub_asaas_123",
                    "externalReference": f"auraxis:{user_id}:premium_monthly",
                    "dueDate": "2026-12-31",
                },
            },
            headers={"asaas-access-token": "asaas-webhook-token"},
        )

        assert resp.status_code == 200
        with app.app_context():
            updated = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert updated is not None
            assert updated.status == SubscriptionStatus.ACTIVE
            assert updated.plan_code == "premium"
            assert updated.billing_cycle == BillingCycle.MONTHLY
            assert updated.provider_subscription_id == "sub_asaas_123"
            assert updated.provider_event_id == "evt_asaas_123"
            user = User.query.filter_by(id=updated.user_id).first()
            assert user is not None
            assert user.entitlements_version == 1
            outbox = app.extensions.get("email_outbox", [])
            assert isinstance(outbox, list)
            assert outbox[-1]["tag"] == "billing_payment_confirmed"

    def test_webhook_rejects_invalid_signature_when_secret_is_configured(
        self,
        client,
        monkeypatch,
    ) -> None:
        monkeypatch.setenv("BILLING_WEBHOOK_SECRET", "billing-webhook-secret")
        monkeypatch.setenv("BILLING_WEBHOOK_ALLOW_UNSIGNED", "false")

        resp = client.post(
            "/subscriptions/webhook",
            json={"event": "unknown.event", "subscription_id": "sub_xyz"},
            headers={"X-Billing-Signature": "invalid-signature"},
        )

        assert resp.status_code == 401
        body = resp.get_json()
        assert body["success"] is False
        assert body["error"]["code"] == "UNAUTHORIZED"

    def test_webhook_logs_warning_for_invalid_signature(
        self,
        client,
        monkeypatch,
        caplog,
    ) -> None:
        monkeypatch.setenv("BILLING_WEBHOOK_SECRET", "billing-webhook-secret")
        monkeypatch.setenv("BILLING_WEBHOOK_ALLOW_UNSIGNED", "false")

        with caplog.at_level(logging.WARNING):
            resp = client.post(
                "/subscriptions/webhook",
                json={"event": "unknown.event", "subscription_id": "sub_xyz"},
                headers={"X-Billing-Signature": "invalid-signature"},
            )

        assert resp.status_code == 401
        logs = [
            record.message
            for record in caplog.records
            if "Billing webhook invalid signature" in record.message
        ]
        assert len(logs) == 1
        assert "request_id=" in logs[0]


# ---------------------------------------------------------------------------
# WebhookEvent audit log (PAY-03)
# ---------------------------------------------------------------------------


class TestWebhookEventAuditLog:
    """Verify that every webhook attempt is persisted to webhook_events."""

    def test_processed_event_creates_webhook_event_record(self, client, app) -> None:
        token = _register_and_login(client, prefix="we-proc")
        r = client.get("/subscriptions/me", headers=_auth_headers(token))
        sub_id = r.get_json()["data"]["subscription"]["id"]

        with app.app_context():
            from app.extensions.database import db

            sub: Subscription = Subscription.query.filter_by(
                id=uuid.UUID(sub_id)
            ).first()  # type: ignore[assignment]
            sub.provider_subscription_id = "we_test_sub_1"
            db.session.commit()

        resp = client.post(
            "/subscriptions/webhook",
            json={
                "event": "PAYMENT_CONFIRMED",
                "id": "evt_we_001",
                "subscription": {"id": "we_test_sub_1", "customer": "cus_001"},
            },
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["processed"] is True

        with app.app_context():
            from app.models.webhook_event import WebhookEvent

            ev = WebhookEvent.query.filter_by(event_id="evt_we_001").first()
            assert ev is not None, "WebhookEvent must be persisted"
            assert ev.status == "processed"
            assert ev.event_type == "PAYMENT_CONFIRMED"
            assert ev.provider == "asaas"
            assert ev.signature_verified is True  # test env allows unsigned
            assert ev.processed_at is not None

    def test_invalid_signature_creates_skipped_record(
        self, client, app, monkeypatch
    ) -> None:
        import hashlib as _hashlib
        import hmac as _hmac

        monkeypatch.setenv("BILLING_WEBHOOK_SECRET", "test_secret_key")
        payload = b'{"event": "PAYMENT_CONFIRMED"}'
        wrong_sig = _hmac.new(b"wrong_key", payload, _hashlib.sha256).hexdigest()

        resp = client.post(
            "/subscriptions/webhook",
            data=payload,
            content_type="application/json",
            headers={"X-Billing-Signature": wrong_sig},
        )
        assert resp.status_code == 401

        with app.app_context():
            from app.models.webhook_event import WebhookEvent

            ev = WebhookEvent.query.order_by(WebhookEvent.received_at.desc()).first()
            assert ev is not None
            assert ev.status == "skipped"
            assert ev.signature_verified is False
            assert ev.failure_reason == "invalid_signature"

    def test_duplicate_event_creates_skipped_record(self, client, app) -> None:
        token = _register_and_login(client, prefix="we-dup")
        r = client.get("/subscriptions/me", headers=_auth_headers(token))
        sub_id = r.get_json()["data"]["subscription"]["id"]

        with app.app_context():
            from app.extensions.database import db

            sub: Subscription = Subscription.query.filter_by(
                id=uuid.UUID(sub_id)
            ).first()  # type: ignore[assignment]
            sub.provider_subscription_id = "we_dup_sub"
            db.session.commit()

        payload = {
            "event": "PAYMENT_CONFIRMED",
            "id": "evt_dup_999",
            "subscription": {"id": "we_dup_sub", "customer": "cus_dup"},
        }
        # First call — should process.
        resp1 = client.post("/subscriptions/webhook", json=payload)
        assert resp1.status_code == 200
        assert resp1.get_json()["data"]["processed"] is True

        # Second call — should be skipped as duplicate.
        resp2 = client.post("/subscriptions/webhook", json=payload)
        assert resp2.status_code == 200
        assert resp2.get_json()["data"]["processed"] is False

        with app.app_context():
            from app.models.webhook_event import WebhookEvent

            events = WebhookEvent.query.filter_by(event_id="evt_dup_999").all()
            assert len(events) == 2
            statuses = {e.status for e in events}
            assert "processed" in statuses
            assert "skipped" in statuses
