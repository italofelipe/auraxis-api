from __future__ import annotations

from typing import Any
from uuid import UUID

import graphene

from app.application.services.transaction_application_service import (
    TransactionApplicationError,
    TransactionApplicationService,
)
from app.controllers.transaction.utils import _build_installment_amounts
from app.graphql.auth import get_current_user_required
from app.graphql.decorators import graphql_error_adapter, resolver_with_user_context
from app.graphql.enums import (
    TransactionStatusEnum,
    TransactionTypeEnum,
    coerce_enum_kwargs,
)
from app.graphql.errors import build_public_graphql_error, to_public_graphql_code
from app.graphql.observability import log_graphql_resolver
from app.graphql.types import TransactionTypeObject


class CreateTransactionMutation(graphene.Mutation):
    class Arguments:
        title = graphene.String(required=True)
        amount = graphene.String(required=True)
        type = TransactionTypeEnum(required=True)
        due_date = graphene.String(required=True)
        description = graphene.String()
        observation = graphene.String()
        is_recurring = graphene.Boolean(default_value=False)
        is_installment = graphene.Boolean(default_value=False)
        installment_count = graphene.Int()
        recurrence_interval = graphene.Int()
        recurrence_unit = graphene.String()
        currency = graphene.String(default_value="BRL")
        status = TransactionStatusEnum()
        start_date = graphene.String()
        end_date = graphene.String()
        category = graphene.String()
        tag_id = graphene.UUID()
        account_id = graphene.UUID()
        credit_card_id = graphene.UUID()
        impact_policy = graphene.String(default_value="full")

    items = graphene.List(TransactionTypeObject, required=True)
    message = graphene.String(required=True)

    def mutate(
        self, info: graphene.ResolveInfo, **kwargs: Any
    ) -> "CreateTransactionMutation":
        user = get_current_user_required()
        service = TransactionApplicationService.with_defaults(UUID(str(user.id)))
        coerce_enum_kwargs(kwargs, "type", "status")
        payload = dict(kwargs)
        payload.setdefault("status", "pending")
        payload["tag_id"] = kwargs.get("tag_id") or kwargs.get("tagId")
        payload["account_id"] = kwargs.get("account_id") or kwargs.get("accountId")
        payload["credit_card_id"] = kwargs.get("credit_card_id") or kwargs.get(
            "creditCardId"
        )
        try:
            result = service.create_transaction(
                payload,
                installment_amount_builder=_build_installment_amounts,
            )
        except TransactionApplicationError as exc:
            raise build_public_graphql_error(
                exc.message,
                code=to_public_graphql_code(exc.code),
            ) from exc

        return CreateTransactionMutation(
            message=str(result["message"]),
            items=[
                TransactionTypeObject(**item)
                for item in result["items"]
                if isinstance(item, dict)
            ],
        )


class DeleteTransactionMutation(graphene.Mutation):
    class Arguments:
        transaction_id = graphene.UUID(required=True)
        # "series" soft-deletes the whole recurring series; default deletes
        # only this occurrence (REST parity with ?scope=).
        scope = graphene.String(required=False)

    ok = graphene.Boolean(required=True)
    message = graphene.String(required=True)

    @log_graphql_resolver("deleteTransaction")
    @resolver_with_user_context(TransactionApplicationService)
    @graphql_error_adapter(TransactionApplicationError)
    def mutate(
        self,
        info: graphene.ResolveInfo,
        service: TransactionApplicationService,
        transaction_id: UUID,
        scope: str | None = None,
    ) -> "DeleteTransactionMutation":
        normalized_scope = (
            "series" if (scope or "").strip().lower() == "series" else "occurrence"
        )
        service.delete_transaction(transaction_id, scope=normalized_scope)
        return DeleteTransactionMutation(
            ok=True, message="Transação deletada com sucesso (soft delete)."
        )


class UpdateTransactionMutation(graphene.Mutation):
    class Arguments:
        transaction_id = graphene.UUID(required=True)
        title = graphene.String()
        amount = graphene.String()
        type = TransactionTypeEnum()
        due_date = graphene.String()
        description = graphene.String()
        observation = graphene.String()
        is_recurring = graphene.Boolean()
        is_installment = graphene.Boolean()
        installment_count = graphene.Int()
        currency = graphene.String()
        status = TransactionStatusEnum()
        start_date = graphene.String()
        end_date = graphene.String()
        category = graphene.String()
        tag_id = graphene.UUID()
        account_id = graphene.UUID()
        credit_card_id = graphene.UUID()
        impact_policy = graphene.String()
        paid_at = graphene.String()

    transaction = graphene.Field(TransactionTypeObject, required=True)
    message = graphene.String(required=True)

    def mutate(
        self,
        info: graphene.ResolveInfo,
        transaction_id: UUID,
        **kwargs: Any,
    ) -> "UpdateTransactionMutation":
        user = get_current_user_required()
        service = TransactionApplicationService.with_defaults(UUID(str(user.id)))
        coerce_enum_kwargs(kwargs, "type", "status")
        try:
            transaction = service.update_transaction(transaction_id, dict(kwargs))
        except TransactionApplicationError as exc:
            raise build_public_graphql_error(
                exc.message,
                code=to_public_graphql_code(exc.code),
            ) from exc
        return UpdateTransactionMutation(
            message="Transação atualizada com sucesso",
            transaction=TransactionTypeObject(**transaction),
        )
