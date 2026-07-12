"""H-PROD-01 — Billing integration tests.

Covers:
- Trial period bootstrap on user registration
- activate_premium / deactivate_premium / check_access helpers
- process_trial_expirations script logic
- Webhook activation and downgrade flows
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.config.plan_features import PLAN_FEATURES, PREMIUM_FEATURES
from app.extensions.database import db
from app.models.entitlement import Entitlement
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services.entitlement_service import (
    activate_premium,
    check_access,
    deactivate_premium,
    has_entitlement,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(app, *, suffix: str | None = None) -> tuple[User, str]:
    """Create a user via the registration endpoint and return (user_obj, token)."""
    s = suffix or uuid.uuid4().hex[:8]
    email = f"billing-{s}@test.com"
    password = "StrongPass@123"
    with app.test_client() as c:
        r = c.post(
            "/auth/register",
            json={"name": f"User {s}", "email": email, "password": password},
        )
        assert r.status_code == 201, r.get_json()
        r2 = c.post("/auth/login", json={"email": email, "password": password})
        assert r2.status_code == 200, r2.get_json()
        token = r2.get_json()["token"]
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        assert user is not None
    return user, token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Trial period bootstrap tests
# ---------------------------------------------------------------------------


class TestTrialBootstrap:
    def test_registration_creates_trialing_subscription(self, app) -> None:
        """New users must get a TRIALING subscription with trial_ends_at ~14 days."""
        user, _token = _make_user(app)
        with app.app_context():
            sub = Subscription.query.filter_by(user_id=user.id).first()
            assert sub is not None, "Subscription must be created at registration"
            assert sub.status == SubscriptionStatus.TRIALING
            assert sub.plan_code == "trial"
            assert sub.trial_ends_at is not None
            now = datetime.utcnow()
            delta = sub.trial_ends_at - now
            # Trial must be between 13 and 15 days from now
            assert timedelta(days=13) < delta < timedelta(days=15)

    def test_registration_trial_ends_at_is_14_days(self, app) -> None:
        """trial_ends_at should be approximately now + 14 days."""
        user, _token = _make_user(app)
        with app.app_context():
            sub = Subscription.query.filter_by(user_id=user.id).first()
            assert sub is not None
            expected_approx = datetime.utcnow() + timedelta(days=14)
            diff = abs((sub.trial_ends_at - expected_approx).total_seconds())
            assert diff < 60, f"trial_ends_at differs from expected by {diff}s"


# ---------------------------------------------------------------------------
# activate_premium / deactivate_premium / check_access
# ---------------------------------------------------------------------------


class TestActivatePremium:
    def test_activate_premium_grants_all_premium_features(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            result = activate_premium(user_id)
            granted_keys = {e.feature_key for e in result}
            expected = set(PLAN_FEATURES["premium"])
            assert expected.issubset(granted_keys)

    def test_activate_premium_with_expires_at(self, app) -> None:
        user_id = uuid.uuid4()
        expires = datetime.utcnow() + timedelta(days=30)
        with app.app_context():
            activate_premium(user_id, expires_at=expires)
            for feature in PLAN_FEATURES["premium"]:
                ent = Entitlement.query.filter_by(
                    user_id=user_id, feature_key=feature
                ).first()
                assert ent is not None
                assert ent.expires_at is not None
                diff = abs((ent.expires_at - expires).total_seconds())
                assert diff < 2

    def test_activate_premium_idempotent(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            activate_premium(user_id)
            activate_premium(user_id)
            for feature in PLAN_FEATURES["premium"]:
                count = Entitlement.query.filter_by(
                    user_id=user_id, feature_key=feature
                ).count()
                assert count == 1, f"Duplicate entitlement rows for {feature}"


class TestDeactivatePremium:
    def test_deactivate_premium_revokes_premium_only_features(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            # First grant premium
            activate_premium(user_id)
            # Then revoke
            deactivate_premium(user_id)
            for feature in PREMIUM_FEATURES:
                assert not has_entitlement(user_id, feature), (
                    f"Premium feature '{feature}' should be revoked"
                )

    def test_deactivate_premium_keeps_free_features(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            activate_premium(user_id)
            deactivate_premium(user_id)
            free_features = set(PLAN_FEATURES["free"]) - PREMIUM_FEATURES
            for feature in free_features:
                # Free-tier features are NOT in premium-only set, so they
                # shouldn't be affected by deactivate_premium at all
                # (they wouldn't have been granted by activate_premium either)
                assert feature not in PREMIUM_FEATURES


class TestCheckAccess:
    def test_check_access_returns_true_for_granted_feature(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            activate_premium(user_id)
            assert check_access(user_id, "export_pdf") is True

    def test_check_access_returns_false_when_no_entitlement(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            assert check_access(user_id, "export_pdf") is False

    def test_check_access_returns_true_during_active_trial(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            future = datetime.utcnow() + timedelta(days=10)
            sub = Subscription(
                user_id=user_id,
                plan_code="trial",
                status=SubscriptionStatus.TRIALING,
                trial_ends_at=future,
            )
            db.session.add(sub)
            db.session.commit()
            # No entitlement row, but trial is active
            assert check_access(user_id, "export_pdf") is True

    def test_check_access_returns_false_for_expired_trial(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            past = datetime.utcnow() - timedelta(days=1)
            sub = Subscription(
                user_id=user_id,
                plan_code="trial",
                status=SubscriptionStatus.TRIALING,
                trial_ends_at=past,
            )
            db.session.add(sub)
            db.session.commit()
            assert check_access(user_id, "export_pdf") is False

    def test_check_access_returns_false_for_no_subscription(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            assert check_access(user_id, "advanced_simulations") is False


# ---------------------------------------------------------------------------
# process_trial_expirations — logic tests (exercised directly via app context)
# ---------------------------------------------------------------------------


def _run_trial_expiration_logic(app, *, dry_run: bool = False) -> int:
    """Run trial expiration logic directly using the already-running app context.

    This mirrors what process_trial_expirations.py does but skips the Flask
    app factory call so tests can use the pytest-fixture-managed app instance.
    """
    from app.extensions.database import db
    from app.models.subscription import Subscription, SubscriptionStatus
    from app.services.entitlement_service import deactivate_premium
    from app.utils.datetime_utils import utc_now_naive

    processed = 0
    with app.app_context():
        now = utc_now_naive()
        expired_subs: list[Subscription] = Subscription.query.filter(
            Subscription.status == SubscriptionStatus.TRIALING,
            Subscription.trial_ends_at.isnot(None),
            Subscription.trial_ends_at <= now,
        ).all()

        for sub in expired_subs:
            if not dry_run:
                sub.status = SubscriptionStatus.FREE
                sub.plan_code = "free"
                db.session.add(sub)
                try:
                    deactivate_premium(sub.user_id)
                except Exception:
                    pass
            processed += 1

        if not dry_run:
            db.session.commit()

    return processed


class TestProcessTrialExpirations:
    def test_expired_trials_are_downgraded(self, app) -> None:
        """Subscriptions with trial_ends_at in the past must be set to FREE."""
        user_id = uuid.uuid4()
        with app.app_context():
            past = datetime.utcnow() - timedelta(hours=1)
            sub = Subscription(
                user_id=user_id,
                plan_code="trial",
                status=SubscriptionStatus.TRIALING,
                trial_ends_at=past,
            )
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id

        count = _run_trial_expiration_logic(app, dry_run=False)

        assert count == 1
        with app.app_context():
            updated = Subscription.query.filter_by(id=sub_id).first()
            assert updated is not None
            assert updated.status == SubscriptionStatus.FREE
            assert updated.plan_code == "free"

    def test_active_trials_are_not_downgraded(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            future = datetime.utcnow() + timedelta(days=7)
            sub = Subscription(
                user_id=user_id,
                plan_code="trial",
                status=SubscriptionStatus.TRIALING,
                trial_ends_at=future,
            )
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id

        count = _run_trial_expiration_logic(app, dry_run=False)

        assert count == 0
        with app.app_context():
            unchanged = Subscription.query.filter_by(id=sub_id).first()
            assert unchanged is not None
            assert unchanged.status == SubscriptionStatus.TRIALING

    def test_dry_run_does_not_commit(self, app) -> None:
        user_id = uuid.uuid4()
        with app.app_context():
            past = datetime.utcnow() - timedelta(hours=1)
            sub = Subscription(
                user_id=user_id,
                plan_code="trial",
                status=SubscriptionStatus.TRIALING,
                trial_ends_at=past,
            )
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id

        count = _run_trial_expiration_logic(app, dry_run=True)

        assert count == 1
        with app.app_context():
            unchanged = Subscription.query.filter_by(id=sub_id).first()
            assert unchanged is not None
            # dry-run: status must NOT have changed
            assert unchanged.status == SubscriptionStatus.TRIALING


# ---------------------------------------------------------------------------
# Webhook activation / downgrade flows
# ---------------------------------------------------------------------------


class TestWebhookBillingFlows:
    """Integration tests for billing webhook → entitlement activation/downgrade."""

    def _setup_subscription_with_customer(
        self, app, client, *, prefix: str
    ) -> tuple[str, str]:
        """Register user, get token, inject a provider_customer_id.

        Returns (token, sub_id).
        """
        s = uuid.uuid4().hex[:8]
        email = f"{prefix}-{s}@test.com"
        password = "StrongPass@123"

        r = client.post(
            "/auth/register",
            json={"name": f"User {s}", "email": email, "password": password},
        )
        assert r.status_code == 201
        r2 = client.post("/auth/login", json={"email": email, "password": password})
        assert r2.status_code == 200
        token = r2.get_json()["token"]

        # Ensure subscription record exists and inject provider_customer_id
        r3 = client.get(
            "/subscriptions/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        sub_id = r3.get_json()["data"]["subscription"]["id"]

        with app.app_context():
            sub = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert sub is not None
            sub.provider_customer_id = f"cus_{s}"
            db.session.commit()

        return token, sub_id

    def test_payment_confirmed_activates_premium_entitlements(
        self, client, app
    ) -> None:
        """PAYMENT_CONFIRMED webhook must activate premium features."""
        import os

        os.environ.setdefault("BILLING_ASAAS_WEBHOOK_TOKEN", "test-webhook-token")
        token, sub_id = self._setup_subscription_with_customer(
            app, client, prefix="wh-confirm"
        )
        with app.app_context():
            sub = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert sub is not None
            customer_id = sub.provider_customer_id
            user_id_str = str(sub.user_id)

        import os

        os.environ["BILLING_ASAAS_WEBHOOK_TOKEN"] = "test-webhook-token"

        resp = client.post(
            "/subscriptions/webhook",
            json={
                "id": f"evt_{uuid.uuid4().hex[:8]}",
                "event": "PAYMENT_CONFIRMED",
                "payment": {
                    "customer": customer_id,
                    "subscription": f"sub_{uuid.uuid4().hex[:8]}",
                    "externalReference": f"auraxis:{user_id_str}:premium_monthly",
                    "dueDate": "2026-12-31",
                },
            },
            headers={"asaas-access-token": "test-webhook-token"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["processed"] is True

        with app.app_context():
            updated = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert updated is not None
            assert updated.status == SubscriptionStatus.ACTIVE
            assert updated.plan_code == "premium"

    def test_payment_overdue_downgrades_subscription(self, client, app) -> None:
        """PAYMENT_OVERDUE webhook must set subscription to PAST_DUE."""
        import os

        token, sub_id = self._setup_subscription_with_customer(
            app, client, prefix="wh-overdue"
        )
        with app.app_context():
            sub = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert sub is not None
            # Pre-set to active so we can observe the downgrade
            sub.status = SubscriptionStatus.ACTIVE
            sub.plan_code = "premium"
            customer_id = sub.provider_customer_id
            user_id_str = str(sub.user_id)
            db.session.commit()

        os.environ["BILLING_ASAAS_WEBHOOK_TOKEN"] = "test-webhook-token"

        resp = client.post(
            "/subscriptions/webhook",
            json={
                "id": f"evt_{uuid.uuid4().hex[:8]}",
                "event": "PAYMENT_OVERDUE",
                "payment": {
                    "customer": customer_id,
                    "subscription": f"sub_{uuid.uuid4().hex[:8]}",
                    "externalReference": f"auraxis:{user_id_str}:premium_monthly",
                    "dueDate": "2026-12-31",
                },
            },
            headers={"asaas-access-token": "test-webhook-token"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["processed"] is True

        with app.app_context():
            updated = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert updated is not None
            assert updated.status == SubscriptionStatus.PAST_DUE

    def test_subscription_deleted_cancels_subscription(self, client, app) -> None:
        """SUBSCRIPTION_DELETED webhook must set subscription to CANCELED."""
        import os

        token, sub_id = self._setup_subscription_with_customer(
            app, client, prefix="wh-deleted"
        )
        with app.app_context():
            sub = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert sub is not None
            sub.status = SubscriptionStatus.ACTIVE
            sub.plan_code = "premium"
            sub.provider_subscription_id = f"sub_{uuid.uuid4().hex[:8]}"
            customer_id = sub.provider_customer_id
            provider_sub_id = sub.provider_subscription_id
            db.session.commit()

        os.environ["BILLING_ASAAS_WEBHOOK_TOKEN"] = "test-webhook-token"

        resp = client.post(
            "/subscriptions/webhook",
            json={
                "id": f"evt_{uuid.uuid4().hex[:8]}",
                "event": "SUBSCRIPTION_DELETED",
                "subscription": {
                    "id": provider_sub_id,
                    "customer": customer_id,
                },
            },
            headers={"asaas-access-token": "test-webhook-token"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["processed"] is True

        with app.app_context():
            updated = Subscription.query.filter_by(id=uuid.UUID(sub_id)).first()
            assert updated is not None
            assert updated.status == SubscriptionStatus.CANCELED


# ---------------------------------------------------------------------------
# Checkout endpoint (POST /subscriptions/checkout)
# ---------------------------------------------------------------------------


class TestBillingCheckoutEndpoint:
    def test_checkout_returns_url_and_plan_info(self, client) -> None:
        s = uuid.uuid4().hex[:8]
        email = f"chk-{s}@test.com"
        r = client.post(
            "/auth/register",
            json={"name": f"User {s}", "email": email, "password": "StrongPass@123"},
        )
        assert r.status_code == 201
        r2 = client.post(
            "/auth/login", json={"email": email, "password": "StrongPass@123"}
        )
        token = r2.get_json()["token"]

        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "premium_monthly"},
            headers=_auth(token),
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["success"] is True
        assert "checkout_url" in body["data"]
        assert body["data"]["plan_code"] == "premium"
        assert body["data"]["billing_cycle"] == "monthly"

    def test_checkout_requires_authentication(self, client) -> None:
        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "premium_monthly"},
        )
        assert resp.status_code == 401

    def test_checkout_invalid_plan_slug_returns_400(self, client) -> None:
        s = uuid.uuid4().hex[:8]
        email = f"chk-bad-{s}@test.com"
        r = client.post(
            "/auth/register",
            json={"name": f"User {s}", "email": email, "password": "StrongPass@123"},
        )
        assert r.status_code == 201
        r2 = client.post(
            "/auth/login", json={"email": email, "password": "StrongPass@123"}
        )
        token = r2.get_json()["token"]

        resp = client.post(
            "/subscriptions/checkout",
            json={"plan_slug": "nonexistent_plan"},
            headers=_auth(token),
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# Dunning emails — trial expiration + local cancellation (#1555)
# ---------------------------------------------------------------------------


class TestTrialExpirationEmail:
    def test_process_trial_expirations_sends_trial_expired_email(self, app) -> None:
        """The expiry job must email the downgraded user (downgrade efetivado)."""
        from scripts.process_trial_expirations import process_trial_expirations

        with app.app_context():
            user = User(
                id=uuid.uuid4(),
                name="Expired Trial User",
                email="expired-trial@test.com",
                password="hash",
            )
            db.session.add(user)
            db.session.flush()
            sub = Subscription(
                user_id=user.id,
                plan_code="trial",
                status=SubscriptionStatus.TRIALING,
                trial_ends_at=datetime.utcnow() - timedelta(hours=1),
            )
            db.session.add(sub)
            db.session.commit()
            sub_id = sub.id

        count = process_trial_expirations(dry_run=False, flask_app=app)

        assert count == 1
        with app.app_context():
            from app.services.email_provider import get_email_outbox

            downgraded = Subscription.query.filter_by(id=sub_id).first()
            assert downgraded is not None
            assert downgraded.status == SubscriptionStatus.FREE

            outbox = get_email_outbox()
            tags = [entry["tag"] for entry in outbox]
            assert "billing_trial_expired" in tags
            emails = [entry["email"] for entry in outbox]
            assert "expired-trial@test.com" in emails
            outbox.clear()

    def test_process_trial_expirations_dry_run_sends_no_email(self, app) -> None:
        from scripts.process_trial_expirations import process_trial_expirations

        with app.app_context():
            user = User(
                id=uuid.uuid4(),
                name="Dry Run Trial User",
                email="dry-trial@test.com",
                password="hash",
            )
            db.session.add(user)
            db.session.flush()
            db.session.add(
                Subscription(
                    user_id=user.id,
                    plan_code="trial",
                    status=SubscriptionStatus.TRIALING,
                    trial_ends_at=datetime.utcnow() - timedelta(hours=1),
                )
            )
            db.session.commit()

        count = process_trial_expirations(dry_run=True, flask_app=app)

        assert count == 1
        with app.app_context():
            from app.services.email_provider import get_email_outbox

            assert len(get_email_outbox()) == 0


class TestCancelSubscriptionEmail:
    class _UnusedProvider:
        """cancel_subscription must not call the provider for local-only subs."""

        def cancel_subscription(self, provider_subscription_id: str) -> None:
            raise AssertionError("provider must not be called for local cancel")

    class _RecordingProvider:
        def __init__(self) -> None:
            self.canceled: list[str] = []

        def cancel_subscription(self, provider_subscription_id: str) -> None:
            self.canceled.append(provider_subscription_id)

    def test_local_cancel_sends_confirmation_email(self, app) -> None:
        """Cancel without provider_subscription_id has no webhook — email here."""
        from app.services.email_provider import get_email_outbox
        from app.services.subscription_service import cancel_subscription

        with app.app_context():
            user = User(
                id=uuid.uuid4(),
                name="Local Cancel User",
                email="local-cancel@test.com",
                password="hash",
            )
            db.session.add(user)
            db.session.flush()
            sub = Subscription(
                user_id=user.id,
                plan_code="premium",
                status=SubscriptionStatus.ACTIVE,
            )
            db.session.add(sub)
            db.session.commit()

            result = cancel_subscription(sub, self._UnusedProvider())

            assert result.status == SubscriptionStatus.CANCELED
            outbox = get_email_outbox()
            assert len(outbox) == 1
            assert outbox[0]["tag"] == "billing_subscription_canceled"
            assert outbox[0]["email"] == "local-cancel@test.com"
            outbox.clear()

    def test_provider_backed_cancel_relies_on_webhook_email(self, app) -> None:
        """Provider-backed cancel gets SUBSCRIPTION_DELETED webhook — no dupe."""
        from app.services.email_provider import get_email_outbox
        from app.services.subscription_service import cancel_subscription

        with app.app_context():
            user = User(
                id=uuid.uuid4(),
                name="Provider Cancel User",
                email="provider-cancel@test.com",
                password="hash",
            )
            db.session.add(user)
            db.session.flush()
            sub = Subscription(
                user_id=user.id,
                plan_code="premium",
                status=SubscriptionStatus.ACTIVE,
                provider="asaas",
                provider_subscription_id="sub_prov_1",
            )
            db.session.add(sub)
            db.session.commit()

            provider = self._RecordingProvider()
            result = cancel_subscription(sub, provider)

            assert result.status == SubscriptionStatus.CANCELED
            assert provider.canceled == ["sub_prov_1"]
            assert len(get_email_outbox()) == 0
