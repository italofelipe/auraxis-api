# mypy: disable-error-code=no-any-return

from __future__ import annotations

from uuid import UUID

from flask import Response, request

from app.application.services.transaction_application_service import (
    TransactionApplicationError,
)
from app.auth import current_user_id
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required

from .dependencies import get_transaction_dependencies
from .openapi import TRANSACTION_SOFT_DELETE_DOC
from .utils import (
    _compat_error,
    _compat_success,
    _guard_revoked_token,
    _internal_error_response,
)


class TransactionDeleteMixin:
    """DELETE behavior for transaction soft delete."""

    @doc(**TRANSACTION_SOFT_DELETE_DOC)
    @jwt_required()
    def delete(self, transaction_id: UUID) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_uuid = current_user_id()
        dependencies = get_transaction_dependencies()
        service = dependencies.transaction_application_service_factory(user_uuid)

        # Optional scope: "series" soft-deletes the whole recurring series,
        # anything else (default) deletes just this occurrence. Lenient so an
        # unknown value never errors a delete.
        scope = request.args.get("scope", "occurrence").strip().lower()
        if scope != "series":
            scope = "occurrence"

        try:
            service.delete_transaction(transaction_id, scope=scope)
        except TransactionApplicationError as exc:
            return _compat_error(
                legacy_payload={"error": exc.message, "details": exc.details},
                status_code=exc.status_code,
                message=exc.message,
                error_code=exc.code,
                details=exc.details,
            )
        except Exception:
            return _internal_error_response(
                message="Erro ao deletar transação",
                log_context="transaction.soft_delete_failed",
            )

        return _compat_success(
            legacy_payload={"message": "Transação deletada com sucesso (soft delete)."},
            status_code=200,
            message="Transação deletada com sucesso (soft delete).",
            data={},
        )
