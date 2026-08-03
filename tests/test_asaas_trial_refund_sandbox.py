"""Cobertura dos três buracos que a migração de 19/07 deixou no Asaas (#1673).

Nenhum destes é uma regressão hipotética: os três só apareceriam com dinheiro
real em produção, e dois deles já custaram caro no gateway anterior.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.controllers.billing_webhook_parsers import (
    ASAAS_CHARGEBACK_EVENTS,
    ASAAS_REFUND_EVENTS,
    AsaasWebhookParser,
)
from app.models.subscription import SubscriptionStatus
from app.services.billing_adapter import (
    AsaasBillingProvider,
    BillingCheckoutCustomer,
    BillingProviderError,
    StubBillingProvider,
    get_default_billing_provider,
)


def _clear_runtime_env(monkeypatch) -> None:
    for var in ("FLASK_ENV", "APP_ENV", "AURAXIS_ENV"):
        monkeypatch.delenv(var, raising=False)


class TestAsaasTrial:
    """O trial vive no request do Asaas — não num produto de painel."""

    @pytest.mark.parametrize(
        ("slug", "expected_cycle"),
        [("premium_monthly", "MONTHLY"), ("premium_annual", "YEARLY")],
    )
    def test_next_due_date_is_pushed_by_trial_days(
        self, monkeypatch, slug: str, expected_cycle: str
    ) -> None:
        """Sem isto o comprador vê "7 dias grátis" e é debitado na hora.

        O cadastro deixou de conceder trial no #1569 (moveu para o produto do
        gateway anterior), então o request é o único lugar que resta.
        """
        _clear_runtime_env(monkeypatch)
        provider = AsaasBillingProvider()
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "asaas_test_key")
        monkeypatch.setenv("BILLING_ASAAS_BASE_URL", "https://api.asaas.com/v3")
        monkeypatch.setenv("BILLING_CHECKOUT_SUCCESS_URL", "https://a.com/ok")
        monkeypatch.setenv("BILLING_CHECKOUT_CANCEL_URL", "https://a.com/no")

        captured: dict[str, object] = {}
        responses = iter([{"id": "cus_1"}, {"id": "chk_1", "link": "https://x/c/1"}])

        def _fake_request(method: str, path: str, *, json_payload=None):
            if path == "/checkouts":
                captured.update(json_payload or {})
            return next(responses)

        monkeypatch.setattr(provider, "_request", _fake_request)
        provider.create_checkout_session(
            BillingCheckoutCustomer(user_id="u1", name="U", email="u@e.com"), slug
        )

        subscription = captured["subscription"]
        assert isinstance(subscription, dict)
        assert subscription["cycle"] == expected_cycle
        assert (
            subscription["nextDueDate"]
            == (date.today() + timedelta(days=7)).isoformat()
        ), "as duas ofertas do catálogo têm trial_days=7"

    def test_next_due_date_is_today_when_offer_has_no_trial(self, monkeypatch) -> None:
        """Trial zero não pode virar data no passado nem adiar cobrança."""
        _clear_runtime_env(monkeypatch)
        provider = AsaasBillingProvider()
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "k")
        monkeypatch.setenv("BILLING_CHECKOUT_SUCCESS_URL", "https://a.com/ok")
        monkeypatch.setenv("BILLING_CHECKOUT_CANCEL_URL", "https://a.com/no")

        from dataclasses import replace

        from app.config.billing_plans import PUBLIC_BILLING_PLANS

        offer = next(o for o in PUBLIC_BILLING_PLANS if o.slug == "premium_monthly")
        no_trial = replace(offer, trial_days=0)

        payload = provider._checkout_payload(no_trial, "cus_1", "u1")
        subscription = payload["subscription"]
        assert isinstance(subscription, dict)
        assert subscription["nextDueDate"] == date.today().isoformat()


class TestAsaasSandboxGuard:
    """A base URL default é o SANDBOX — esquecê-la em prod vende para teste."""

    def test_production_refuses_sandbox_base_url(self, monkeypatch) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("FLASK_ENV", raising=False)
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "k")
        monkeypatch.delenv("BILLING_ASAAS_BASE_URL", raising=False)

        provider = AsaasBillingProvider()
        with pytest.raises(BillingProviderError, match="sandbox"):
            provider._ensure_enabled()

    def test_production_accepts_production_base_url(self, monkeypatch) -> None:
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("FLASK_ENV", raising=False)
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "k")
        monkeypatch.setenv("BILLING_ASAAS_BASE_URL", "https://api.asaas.com/v3")

        AsaasBillingProvider()._ensure_enabled()

    def test_sandbox_base_url_is_fine_outside_production(self, monkeypatch) -> None:
        _clear_runtime_env(monkeypatch)
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "k")
        monkeypatch.delenv("BILLING_ASAAS_BASE_URL", raising=False)

        AsaasBillingProvider()._ensure_enabled()

    def test_checkout_fallback_url_follows_the_environment(self, monkeypatch) -> None:
        """O fallback era ``www.asaas.com`` fixo — produção, mesmo em sandbox."""
        _clear_runtime_env(monkeypatch)
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "k")

        monkeypatch.delenv("BILLING_ASAAS_BASE_URL", raising=False)
        assert (
            AsaasBillingProvider()._checkout_page_url("chk_1")
            == "https://sandbox.asaas.com/c/chk_1"
        )

        monkeypatch.setenv("BILLING_ASAAS_BASE_URL", "https://api.asaas.com/v3")
        assert (
            AsaasBillingProvider()._checkout_page_url("chk_1")
            == "https://www.asaas.com/c/chk_1"
        )


class TestAsaasRevocationEvents:
    """Estorno no painel deixava o Premium ativo — #1598 só cobriu o outro gateway."""

    @pytest.mark.parametrize(
        "event", sorted(ASAAS_REFUND_EVENTS | ASAAS_CHARGEBACK_EVENTS)
    )
    def test_refund_and_chargeback_revoke_access(self, event: str) -> None:
        parser = AsaasWebhookParser()
        assert parser.supports_event(event), f"{event} não é reconhecido"

        snapshot = parser.parse(
            {
                "event": event,
                "payment": {
                    "subscription": "sub_1",
                    "customer": "cus_1",
                    "externalReference": "auraxis:u1:premium_monthly",
                },
            }
        )
        assert snapshot is not None
        assert snapshot["status"] == SubscriptionStatus.CANCELED.value
        assert snapshot["provider"] == "asaas"

    def test_refund_in_progress_revokes_immediately(self) -> None:
        """Manter acesso durante a liquidação seria Premium de graça."""
        assert "PAYMENT_REFUND_IN_PROGRESS" in ASAAS_REFUND_EVENTS

    def test_paid_events_still_grant_access(self) -> None:
        """Guard-rail: a revogação não pode ter contaminado o caminho feliz."""
        parser = AsaasWebhookParser()
        snapshot = parser.parse(
            {"event": "PAYMENT_CONFIRMED", "payment": {"subscription": "sub_1"}}
        )
        assert snapshot is not None
        assert snapshot["status"] == SubscriptionStatus.ACTIVE.value


class TestProviderFactory:
    """Sucessor de ``test_asaas_remains_pluggable`` (#1675).

    O teste original afirmava ``not isinstance(..., AbacatePayBillingProvider)``
    e existia para impedir que a migração de 19/07 apagasse o gateway de
    contingência — o que, no fim, foi o que permitiu voltar. Com o AbacatePay
    removido a assertiva perde o objeto, mas o que ela protegia continua
    valendo, e ganha uma proteção nova: provider desconhecido **não pode**
    degradar para stub em produção.
    """

    def test_asaas_is_selected(self, monkeypatch) -> None:
        _clear_runtime_env(monkeypatch)
        monkeypatch.setenv("BILLING_PROVIDER", "asaas")
        monkeypatch.setenv("BILLING_ASAAS_API_KEY", "k")
        assert isinstance(get_default_billing_provider(), AsaasBillingProvider)

    def test_stub_is_selected_explicitly(self, monkeypatch) -> None:
        _clear_runtime_env(monkeypatch)
        monkeypatch.setenv("BILLING_PROVIDER", "stub")
        assert isinstance(get_default_billing_provider(), StubBillingProvider)

    def test_unset_falls_back_to_stub(self, monkeypatch) -> None:
        _clear_runtime_env(monkeypatch)
        monkeypatch.delenv("BILLING_PROVIDER", raising=False)
        monkeypatch.delenv("AURAXIS_BILLING_PROVIDER", raising=False)
        assert isinstance(get_default_billing_provider(), StubBillingProvider)

    @pytest.mark.parametrize("name", ["abacatepay", "stripe", "typo-asaas", "asas"])
    def test_unknown_provider_raises_in_production(self, monkeypatch, name) -> None:
        """Sem isto, um typo serve checkout de stub a comprador real.

        É o cenário exato de deployar a remoção do gateway antigo antes de
        trocar o .env.prod: BILLING_PROVIDER=abacatepay deixaria de resolver e
        a URL devolvida seria ``https://stub.billing/...``, sem erro nenhum.
        """
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.delenv("FLASK_ENV", raising=False)
        monkeypatch.setenv("BILLING_PROVIDER", name)

        with pytest.raises(BillingProviderError, match="not a supported gateway"):
            get_default_billing_provider()

    def test_unknown_provider_still_stubs_outside_production(self, monkeypatch) -> None:
        """CI e desenvolvimento continuam tolerantes — só produção é dura."""
        _clear_runtime_env(monkeypatch)
        monkeypatch.setenv("BILLING_PROVIDER", "whatever")
        assert isinstance(get_default_billing_provider(), StubBillingProvider)
