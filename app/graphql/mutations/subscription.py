"""GraphQL mutations for Subscription/Billing domain (#835).

Mirrors REST endpoints:
  POST /subscriptions/checkout → createCheckoutSession
  POST /subscriptions/cancel   → cancelSubscription
"""

from __future__ import annotations

from uuid import UUID

import graphene

from app.config.billing_plans import resolve_checkout_plan_offer
from app.extensions.database import db
from app.graphql.auth import get_current_user_required
from app.graphql.enums import SubscriptionBillingCycleEnum, coerce_enum_value
from app.graphql.errors import (
    GRAPHQL_ERROR_CODE_CONFLICT,
    GRAPHQL_ERROR_CODE_VALIDATION,
    build_public_graphql_error,
)
from app.graphql.queries.subscription import (
    _serialize_subscription,
    _to_subscription_type,
)
from app.graphql.types import CheckoutSessionType, SubscriptionType
from app.models.subscription import SubscriptionStatus
from app.services.billing_adapter import (
    BillingCheckoutCustomer,
    BillingProviderError,
    get_default_billing_provider,
)
from app.services.subscription_service import (
    cancel_subscription,
    get_or_create_subscription,
)


class CreateCheckoutSessionMutation(graphene.Mutation):
    class Arguments:
        plan_slug = graphene.String(required=True)
        billing_cycle = SubscriptionBillingCycleEnum()

    message = graphene.String(required=True)
    checkout = graphene.Field(CheckoutSessionType, required=True)

    def mutate(
        self,
        info: graphene.ResolveInfo,
        plan_slug: str,
        billing_cycle: object | None = None,
    ) -> "CreateCheckoutSessionMutation":
        user = get_current_user_required()
        billing_cycle_value = coerce_enum_value(billing_cycle)
        billing_cycle = (
            str(billing_cycle_value) if billing_cycle_value is not None else None
        )

        # Resolve plan offer (same logic as REST controller)
        if billing_cycle:
            composed = f"{plan_slug}_{billing_cycle.strip().lower()}"
            offer = resolve_checkout_plan_offer(
                composed
            ) or resolve_checkout_plan_offer(plan_slug)
        else:
            offer = resolve_checkout_plan_offer(plan_slug)

        if offer is None:
            raise build_public_graphql_error(
                "plan_slug inválido", code=GRAPHQL_ERROR_CODE_VALIDATION
            )

        provider = get_default_billing_provider()
        try:
            result = provider.create_checkout_session(
                customer=BillingCheckoutCustomer(
                    user_id=str(UUID(str(user.id))),
                    name=str(user.name),
                    email=str(user.email),
                ),
                plan_slug=offer.slug,
            )
        except BillingProviderError as exc:
            raise build_public_graphql_error(
                str(exc) or "Erro ao criar sessão de checkout",
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            ) from exc

        subscription = get_or_create_subscription(UUID(str(user.id)))
        provider_name = str(result.get("provider") or "").strip()
        provider_customer_id = result.get("provider_customer_id")
        if provider_name:
            subscription.provider = provider_name
        if isinstance(provider_customer_id, str) and provider_customer_id.strip():
            subscription.provider_customer_id = provider_customer_id.strip()
        db.session.commit()

        return CreateCheckoutSessionMutation(
            message="Sessão de checkout criada com sucesso",
            checkout=CheckoutSessionType(
                checkout_url=result.get("checkout_url") or "",
                provider=result.get("provider") or "",
                provider_customer_id=result.get("provider_customer_id"),
                provider_subscription_id=result.get("provider_subscription_id"),
            ),
        )


class CancelSubscriptionMutation(graphene.Mutation):
    class Arguments:
        pass

    ok = graphene.Boolean(required=True)
    message = graphene.String(required=True)
    subscription = graphene.Field(SubscriptionType, required=True)

    def mutate(self, info: graphene.ResolveInfo) -> "CancelSubscriptionMutation":
        user = get_current_user_required()
        sub = get_or_create_subscription(UUID(str(user.id)))

        if sub.status == SubscriptionStatus.CANCELED:
            raise build_public_graphql_error(
                "Assinatura já está cancelada", code=GRAPHQL_ERROR_CODE_CONFLICT
            )

        provider = get_default_billing_provider()
        try:
            sub = cancel_subscription(sub, provider)
        except Exception as exc:
            raise build_public_graphql_error(
                "Erro ao cancelar assinatura", code=GRAPHQL_ERROR_CODE_VALIDATION
            ) from exc

        return CancelSubscriptionMutation(
            ok=True,
            message="Assinatura cancelada com sucesso",
            subscription=_to_subscription_type(_serialize_subscription(sub)),
        )
