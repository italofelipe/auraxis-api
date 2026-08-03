"""Billing provider adapter — J9/J20/J21 (billing / plan management).

Defines a typed provider boundary for billing integrations. The default stub is
used in CI and local development, while the Asaas adapter powers the real MVP1
hosted checkout flow when explicitly enabled via environment variables.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol, TypedDict, cast, runtime_checkable

import requests
from requests import Response
from requests.exceptions import RequestException

from app.config.billing_plans import BillingPlanOffer, resolve_checkout_plan_offer
from app.models.subscription import BillingCycle
from app.services.retry_wrapper import with_retry

logger = logging.getLogger(__name__)

_ASAAS_PROVIDER = "asaas"
_STUB_PROVIDER = "stub"
_PRODUCTION_ENV_NAMES = {"prod", "production"}


def _is_production_runtime() -> bool:
    """Espelha ``billing_webhook_parsers._is_production_runtime``.

    Duplicado de propósito: o parser vive em ``app/controllers`` e importá-lo
    daqui inverteria a direção da dependência (services → controllers). São
    cinco linhas; a alternativa era um módulo compartilhado só para isto.
    """
    for var in ("FLASK_ENV", "APP_ENV", "AURAXIS_ENV"):
        value = str(os.getenv(var) or "").strip().lower()
        if value:
            return value in _PRODUCTION_ENV_NAMES
    return False


_DEFAULT_ASAAS_BASE_URL = "https://api-sandbox.asaas.com/v3"
_REQUEST_TIMEOUT_SECONDS = 15.0


class BillingProviderError(RuntimeError):
    """Raised when a billing provider request fails in a recoverable way."""


class BillingSubscriptionSnapshot(TypedDict, total=False):
    provider_id: str
    provider: str
    provider_customer_id: str | None
    status: str
    plan_code: str
    offer_code: str
    billing_cycle: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    trial_ends_at: datetime | None


class BillingCheckoutSession(TypedDict, total=False):
    checkout_url: str
    provider: str
    provider_customer_id: str | None
    provider_subscription_id: str | None


@dataclass(frozen=True)
class BillingCheckoutCustomer:
    user_id: str
    name: str
    email: str


@runtime_checkable
class BillingProvider(Protocol):
    """Structural interface for billing provider adapters."""

    def get_subscription(self, provider_id: str) -> BillingSubscriptionSnapshot:
        """Fetch current subscription state from the provider.

        Returns a dict with at least a ``status`` key.
        """
        ...

    def cancel_subscription(self, provider_id: str) -> BillingSubscriptionSnapshot:
        """Request immediate cancellation of the subscription.

        Returns a dict with at least a ``status`` key.
        """
        ...

    def create_checkout_session(
        self,
        customer: BillingCheckoutCustomer,
        plan_slug: str,
        return_surface: str | None = None,
    ) -> BillingCheckoutSession:
        """Create a hosted checkout session for the given plan.

        ``return_surface`` selects which configured return URLs the provider
        sends the buyer back to (#1620). Returns a dict with at least a
        ``checkout_url`` key.
        """
        ...


class StubBillingProvider:
    """Stub implementation for development and testing.

    Returns predictable, deterministic responses without making any external
    network calls.  Safe to use in CI and unit-test environments.
    """

    def get_subscription(self, provider_id: str) -> BillingSubscriptionSnapshot:
        return {
            "provider_id": provider_id,
            "status": "active",
            "plan_code": "premium",
            "offer_code": "premium_monthly",
            "billing_cycle": "monthly",
            "current_period_start": None,
            "current_period_end": None,
            "provider": _STUB_PROVIDER,
        }

    def cancel_subscription(self, provider_id: str) -> BillingSubscriptionSnapshot:
        return {
            "provider_id": provider_id,
            "status": "canceled",
            "provider": _STUB_PROVIDER,
        }

    def create_checkout_session(
        self,
        customer: BillingCheckoutCustomer,
        plan_slug: str,
        return_surface: str | None = None,
    ) -> BillingCheckoutSession:
        return {
            "checkout_url": (
                f"https://stub.billing/checkout/{plan_slug}?user={customer.user_id}"
            ),
            "provider": _STUB_PROVIDER,
            "provider_customer_id": f"stub_cus_{customer.user_id}",
        }


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


# Surfaces a checkout can start from, mapped to the env vars holding their
# return URLs. This is an allowlist on purpose: the caller picks a *key*, never
# a URL, so a client can never turn the completion URL into an open redirect.
_CHECKOUT_RETURN_ENVS: dict[str, tuple[str, str]] = {
    "app": ("BILLING_CHECKOUT_SUCCESS_URL", "BILLING_CHECKOUT_CANCEL_URL"),
    "landing": (
        "BILLING_CHECKOUT_LANDING_SUCCESS_URL",
        "BILLING_CHECKOUT_LANDING_CANCEL_URL",
    ),
}

_DEFAULT_CHECKOUT_SURFACE = "app"


def resolve_checkout_return_urls(surface: str | None) -> tuple[str, str]:
    """Resolve the ``(success_url, cancel_url)`` pair for a checkout surface.

    Buyers coming from the landing have no session on the app domain, so they
    must return to the landing after paying (#1620).

    Unknown surfaces — including anything that looks like a client-supplied
    URL — fall back to the app pair, as does a surface whose own URLs are not
    fully configured. Callers are responsible for rejecting an empty pair.

    :param surface: Surface key (``app`` or ``landing``); case-insensitive.
    :returns: The success and cancel URLs, possibly empty when unconfigured.
    """
    normalized = str(surface or "").strip().lower()
    default = tuple(_env(name) for name in _CHECKOUT_RETURN_ENVS["app"])
    if normalized in _CHECKOUT_RETURN_ENVS and normalized != _DEFAULT_CHECKOUT_SURFACE:
        success_env, cancel_env = _CHECKOUT_RETURN_ENVS[normalized]
        success, cancel = _env(success_env), _env(cancel_env)
        if success and cancel:
            return success, cancel
    return default[0], default[1]


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace("+0000", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def _offer_metadata_from_reference(
    external_reference: object,
) -> tuple[str | None, str | None]:
    raw_reference = str(external_reference or "").strip()
    if not raw_reference:
        return None, None
    offer = resolve_checkout_plan_offer(raw_reference.split(":")[-1])
    if offer is None:
        return None, None
    return offer.plan_code, offer.slug


def _raise_for_error_response(response: Response) -> None:
    if response.ok:
        return
    try:
        payload = cast(dict[str, object], response.json())
    except ValueError:
        payload = {}
    message = str(
        payload.get("errors") or payload.get("message") or response.text
    ).strip()
    error_message = message or "unknown error"
    raise BillingProviderError(
        f"Asaas request failed with status {response.status_code}: {error_message}"
    )


class AsaasBillingProvider:
    """Real billing provider backed by Asaas hosted checkout and webhooks."""

    def __init__(self) -> None:
        # Accept both BILLING_ASAAS_API_KEY (canonical) and AURAXIS_ASAAS_API_KEY
        # (platform-level alias set in auraxis-platform .env).
        self._api_key = _env("BILLING_ASAAS_API_KEY") or _env("AURAXIS_ASAAS_API_KEY")
        self._base_url = _env("BILLING_ASAAS_BASE_URL", _DEFAULT_ASAAS_BASE_URL)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "accept": "application/json",
                "content-type": "application/json",
                "access_token": self._api_key,
            }
        )

    @property
    def _is_sandbox(self) -> bool:
        return "sandbox" in self._base_url.lower()

    def _checkout_page_url(self, checkout_id: str) -> str:
        """Página hospedada correspondente à base configurada.

        Antes isto era ``https://www.asaas.com/c/{id}`` fixo, que manda o
        comprador para **produção mesmo rodando em sandbox** — um teste que
        parece passar e leva a um checkout que não existe naquele ambiente.
        """
        host = "sandbox.asaas.com" if self._is_sandbox else "www.asaas.com"
        return f"https://{host}/c/{checkout_id}"

    def _ensure_enabled(self) -> None:
        if not self._api_key:
            raise BillingProviderError(
                "BILLING_ASAAS_API_KEY (or AURAXIS_ASAAS_API_KEY) is required "
                "when BILLING_PROVIDER=asaas"
            )
        # Guard anti-sandbox. `_DEFAULT_ASAAS_BASE_URL` é o sandbox, então
        # esquecer `BILLING_ASAAS_BASE_URL` em produção faz a API vender para
        # o ambiente de teste **em silêncio**: o checkout abre, o comprador
        # "paga", e nada acontece do lado real. Foi assim que se perderam dez
        # dias no gateway anterior (docs/wiki/PAY-AbacatePay-Setup.md, tombstone), com o
        # agravante de que lá havia chave prefixada e guard de devMode no
        # webhook — aqui não há nenhum dos dois. Falhar alto é a única defesa.
        if self._is_sandbox and _is_production_runtime():
            logger.error(
                "event=billing_sandbox_base_url_in_production provider=%s "
                "reason=sandbox_base_url_blocked — BILLING_ASAAS_BASE_URL is "
                "missing or points at sandbox while the app runs in production",
                _ASAAS_PROVIDER,
            )
            raise BillingProviderError(
                "BILLING_ASAAS_BASE_URL points at the Asaas sandbox while "
                "APP_ENV is production — refusing to sell against sandbox. "
                "Set it to https://api.asaas.com/v3"
            )

    def _request(
        self, method: str, path: str, *, json_payload: object | None = None
    ) -> dict[str, object]:
        self._ensure_enabled()
        url = f"{self._base_url.rstrip('/')}/{path.lstrip('/')}"

        @with_retry(provider="asaas")
        def _do() -> dict[str, object]:
            # Let RequestException propagate so tenacity can retry on
            # transient failures. Caught and wrapped after retries exhaust.
            response = self._session.request(
                method=method,
                url=url,
                json=json_payload,
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            _raise_for_error_response(response)
            return cast(dict[str, object], response.json())

        try:
            return _do()
        except RequestException as exc:
            raise BillingProviderError("Asaas request failed") from exc

    def _ensure_customer(self, customer: BillingCheckoutCustomer) -> str:
        payload = self._request(
            "POST",
            "/customers",
            json_payload={
                "name": customer.name,
                "email": customer.email,
                "externalReference": customer.user_id,
                "notificationDisabled": False,
            },
        )
        customer_id = str(payload.get("id") or "").strip()
        if not customer_id:
            raise BillingProviderError("Asaas customer response did not include an id")
        return customer_id

    def _checkout_callback_payload(
        self, return_surface: str | None = None
    ) -> dict[str, str]:
        success_url, cancel_url = resolve_checkout_return_urls(return_surface)
        expired_url = _env("BILLING_CHECKOUT_EXPIRED_URL", cancel_url)
        callback: dict[str, str] = {}
        if success_url:
            callback["successUrl"] = success_url
        if cancel_url:
            callback["cancelUrl"] = cancel_url
        if expired_url:
            callback["expiredUrl"] = expired_url
        return callback

    def _checkout_payload(
        self,
        offer: BillingPlanOffer,
        customer_id: str,
        user_id: str,
        return_surface: str | None = None,
    ) -> dict[str, object]:
        cycle = "YEARLY" if offer.billing_cycle == BillingCycle.ANNUAL else "MONTHLY"
        callback = self._checkout_callback_payload(return_surface)
        if not callback:
            raise BillingProviderError(
                "BILLING_CHECKOUT_SUCCESS_URL and "
                "BILLING_CHECKOUT_CANCEL_URL must be configured"
            )

        return {
            "billingTypes": ["CREDIT_CARD", "PIX"],
            "chargeTypes": ["RECURRENT"],
            "externalReference": f"auraxis:{user_id}:{offer.slug}",
            "callback": callback,
            "customer": customer_id,
            "items": [
                {
                    "name": offer.display_name,
                    "description": offer.description,
                    "quantity": 1,
                    "value": offer.price_cents / 100,
                }
            ],
            # O trial vive AQUI, no request — não num produto cadastrado no
            # painel, como era no gateway anterior. `nextDueDate` é a data da
            # primeira cobrança: adiá-la em `trial_days` é o que dá o período
            # gratuito, com o cartão já tokenizado no checkout.
            #
            # Sem isto o trial não existe em lugar nenhum: o cadastro deixou de
            # concedê-lo no #1569 (register_resource.py:126-131, que o moveu
            # para o produto do gateway), então `trial_days=7` do catálogo
            # (billing_plans.py) seria serializado para o cliente e ignorado na
            # cobrança — o usuário veria "7 dias grátis" e seria debitado na hora.
            "subscription": {
                "cycle": cycle,
                "nextDueDate": (
                    date.today() + timedelta(days=max(offer.trial_days, 0))
                ).isoformat(),
            },
        }

    def get_subscription(self, provider_id: str) -> BillingSubscriptionSnapshot:
        payload = self._request("GET", f"/subscriptions/{provider_id}")
        plan_code, offer_code = _offer_metadata_from_reference(
            payload.get("externalReference")
        )
        return {
            "provider_id": str(payload.get("id") or provider_id),
            "provider": _ASAAS_PROVIDER,
            "provider_customer_id": (
                str(payload.get("customer") or "").strip() or None
            ),
            "status": str(payload.get("status") or "").strip().lower(),
            "plan_code": plan_code or "",
            "offer_code": offer_code or "",
            "billing_cycle": str(payload.get("cycle") or "").strip().lower() or None,
            "current_period_start": _parse_datetime(payload.get("dateCreated")),
            "current_period_end": _parse_datetime(payload.get("nextDueDate")),
        }

    def cancel_subscription(self, provider_id: str) -> BillingSubscriptionSnapshot:
        payload = self._request("DELETE", f"/subscriptions/{provider_id}")
        return {
            "provider_id": str(payload.get("id") or provider_id),
            "status": "canceled",
            "provider": _ASAAS_PROVIDER,
            "provider_customer_id": (
                str(payload.get("customer") or "").strip() or None
            ),
        }

    def create_checkout_session(
        self,
        customer: BillingCheckoutCustomer,
        plan_slug: str,
        return_surface: str | None = None,
    ) -> BillingCheckoutSession:
        offer = resolve_checkout_plan_offer(plan_slug)
        if offer is None:
            raise BillingProviderError(f"Unsupported plan slug: {plan_slug}")
        customer_id = self._ensure_customer(customer)
        payload = self._request(
            "POST",
            "/checkouts",
            json_payload=self._checkout_payload(
                offer, customer_id, customer.user_id, return_surface
            ),
        )
        checkout_id = str(payload.get("id") or "").strip()
        if not checkout_id:
            raise BillingProviderError("Asaas checkout response did not include an id")
        return {
            "checkout_url": (
                str(payload.get("link") or "").strip()
                or self._checkout_page_url(checkout_id)
            ),
            "provider": _ASAAS_PROVIDER,
            "provider_customer_id": customer_id,
            "provider_subscription_id": checkout_id,
        }


def get_default_billing_provider() -> BillingProvider:
    """Factory that returns the active billing provider.

    Reads ``BILLING_PROVIDER`` (canonical).  When unset, falls back to
    ``AURAXIS_BILLING_PROVIDER`` so the platform-level ``.env`` can drive
    the provider without duplicating config into each service env file.

    Um nome desconhecido **levanta** em produção, em vez de cair no stub.
    Antes ele degradava em silêncio, e o custo disso era assimétrico: o
    checkout devolveria uma URL ``https://stub.billing/...`` para um comprador
    real, sem erro em lugar nenhum. Foi exatamente o risco de deployar a
    remoção do gateway anterior antes de trocar o ``.env.prod`` — um typo em
    ``BILLING_PROVIDER`` tem o mesmo efeito. Fora de produção o stub segue
    sendo o default útil para CI e desenvolvimento.
    """
    provider_name = (
        _env("BILLING_PROVIDER") or _env("AURAXIS_BILLING_PROVIDER") or _STUB_PROVIDER
    ).lower()
    if provider_name == _ASAAS_PROVIDER:
        return AsaasBillingProvider()
    if provider_name == _STUB_PROVIDER:
        return StubBillingProvider()

    if _is_production_runtime():
        logger.error(
            "event=billing_unknown_provider_in_production provider=%s "
            "reason=refusing_stub_fallback — BILLING_PROVIDER is not a known "
            "gateway and production must never silently serve a stub checkout",
            provider_name,
        )
        raise BillingProviderError(
            f"BILLING_PROVIDER={provider_name!r} is not a supported gateway. "
            f"Supported: {_ASAAS_PROVIDER!r}. Refusing to fall back to the stub "
            "provider in production."
        )

    logger.warning(
        "BILLING_PROVIDER=%s is unknown; falling back to the stub provider "
        "(non-production runtime)",
        provider_name,
    )
    return StubBillingProvider()
