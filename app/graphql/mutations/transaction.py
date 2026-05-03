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
from app.graphql.errors import build_public_graphql_error, to_public_graphql_code
from app.graphql.observability import log_graphql_resolver
from app.graphql.types import TransactionTypeObject


class CreateTransactionMutation(graphene.Mutation):
    class Arguments:
        title = graphene.String(required=True)
        amount = graphene.String(required=True)
        type = graphene.String(required=True)
        due_date = graphene.String(required=True)
        description = graphene.String()
        observation = graphene.String()
        is_recurring = graphene.Boolean(default_value=False)
        is_installment = graphene.Boolean(default_value=False)
        installment_count = graphene.Int()
        currency = graphene.String(default_value="BRL")
        status = graphene.String(default_value="pending")
        start_date = graphene.String()
        end_date = graphene.String()
        tag_id = graphene.UUID()
        account_id = graphene.UUID()
        credit_card_id = graphene.UUID()

    items = graphene.List(TransactionTypeObject, required=True)
    message = graphene.String(required=True)

    def mutate(
        self, info: graphene.ResolveInfo, **kwargs: Any
    ) -> "CreateTransactionMutation":
        user = get_current_user_required()
        service = TransactionApplicationService.with_defaults(UUID(str(user.id)))
        payload = dict(kwargs)
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

    ok = graphene.Boolean(required=True)
    message = graphene.String(required=True)

    @log_graphql_resolver("deleteTransaction")
    def mutate(
        self, info: graphene.ResolveInfo, transaction_id: UUID
    ) -> "DeleteTransactionMutation":
        user = get_current_user_required()
        service = TransactionApplicationService.with_defaults(UUID(str(user.id)))
        try:
            service.delete_transaction(transaction_id)
        except TransactionApplicationError as exc:
            raise build_public_graphql_error(
                exc.message,
                code=to_public_graphql_code(exc.code),
            ) from exc
        return DeleteTransactionMutation(
            ok=True, message="Transação deletada com sucesso (soft delete)."
        )


class UpdateTransactionMutation(graphene.Mutation):
    class Arguments:
        transaction_id = graphene.UUID(required=True)
        title = graphene.String()
        amount = graphene.String()
        type = graphene.String()
        due_date = graphene.String()
        description = graphene.String()
        observation = graphene.String()
        is_recurring = graphene.Boolean()
        is_installment = graphene.Boolean()
        installment_count = graphene.Int()
        currency = graphene.String()
        status = graphene.String()
        start_date = graphene.String()
        end_date = graphene.String()
        tag_id = graphene.UUID()
        account_id = graphene.UUID()
        credit_card_id = graphene.UUID()
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
