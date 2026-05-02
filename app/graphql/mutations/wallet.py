from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import graphene

from app.application.services.wallet_application_service import (
    WalletApplicationError,
    WalletApplicationService,
)
from app.graphql.auth import get_current_user_required
from app.graphql.scalars import DecimalScalar
from app.graphql.types import WalletType
from app.graphql.wallet_presenters import raise_wallet_graphql_error, to_wallet_type


class AddWalletEntryMutation(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        value = DecimalScalar()
        ticker = graphene.String()
        quantity = graphene.Int()
        asset_class = graphene.String()
        annual_rate = DecimalScalar()
        register_date = graphene.String()
        target_withdraw_date = graphene.String()
        should_be_on_wallet = graphene.Boolean(required=True)

    item = graphene.Field(WalletType, required=True)

    def mutate(
        self, info: graphene.ResolveInfo, **kwargs: Any
    ) -> "AddWalletEntryMutation":
        user = get_current_user_required()
        raw_data = {
            "name": kwargs["name"],
            "value": kwargs.get("value"),
            "ticker": kwargs.get("ticker"),
            "quantity": kwargs.get("quantity"),
            "asset_class": kwargs.get("asset_class", "custom"),
            "annual_rate": kwargs.get("annual_rate"),
            "register_date": kwargs.get("register_date") or date.today().isoformat(),
            "target_withdraw_date": kwargs.get("target_withdraw_date"),
            "should_be_on_wallet": kwargs["should_be_on_wallet"],
        }
        service = WalletApplicationService.with_defaults(UUID(str(user.id)))
        try:
            wallet_data = service.create_entry(raw_data)
        except WalletApplicationError as exc:
            raise_wallet_graphql_error(exc)
        return AddWalletEntryMutation(item=to_wallet_type(wallet_data))


class UpdateWalletEntryMutation(graphene.Mutation):
    class Arguments:
        investment_id = graphene.UUID(required=True)
        name = graphene.String()
        value = DecimalScalar()
        ticker = graphene.String()
        quantity = graphene.Int()
        asset_class = graphene.String()
        annual_rate = DecimalScalar()
        register_date = graphene.String()
        target_withdraw_date = graphene.String()
        should_be_on_wallet = graphene.Boolean()

    item = graphene.Field(WalletType, required=True)

    def mutate(
        self, info: graphene.ResolveInfo, investment_id: UUID, **kwargs: Any
    ) -> "UpdateWalletEntryMutation":
        user = get_current_user_required()
        raw_payload: dict[str, Any] = {
            "name": kwargs.get("name"),
            "value": kwargs.get("value"),
            "ticker": kwargs.get("ticker"),
            "quantity": kwargs.get("quantity"),
            "asset_class": kwargs.get("asset_class"),
            "annual_rate": kwargs.get("annual_rate"),
            "register_date": kwargs.get("register_date"),
            "target_withdraw_date": kwargs.get("target_withdraw_date"),
            "should_be_on_wallet": kwargs.get("should_be_on_wallet"),
        }
        payload = {
            key: value for key, value in raw_payload.items() if value is not None
        }
        service = WalletApplicationService.with_defaults(UUID(str(user.id)))
        try:
            wallet_data = service.update_entry(investment_id, payload)
        except WalletApplicationError as exc:
            raise_wallet_graphql_error(exc)
        return UpdateWalletEntryMutation(item=to_wallet_type(wallet_data))


class DeleteWalletEntryMutation(graphene.Mutation):
    class Arguments:
        investment_id = graphene.UUID(required=True)

    ok = graphene.Boolean(required=True)
    message = graphene.String(required=True)

    def mutate(
        self, info: graphene.ResolveInfo, investment_id: UUID
    ) -> "DeleteWalletEntryMutation":
        user = get_current_user_required()
        service = WalletApplicationService.with_defaults(UUID(str(user.id)))
        try:
            service.delete_entry(
                investment_id,
                forbidden_message=(
                    "Você não tem permissão para remover este investimento."
                ),
            )
        except WalletApplicationError as exc:
            raise_wallet_graphql_error(exc)
        return DeleteWalletEntryMutation(
            ok=True, message="Investimento removido com sucesso"
        )
