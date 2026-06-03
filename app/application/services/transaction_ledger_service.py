"""Transaction Ledger Service.

CRUD + list queries for ``Transaction`` records. Analytics / dashboard
aggregation live on ``TransactionAnalyticsService``; the public facade
``TransactionApplicationService`` composes both.

Domain helpers are sub-moduled under ``app.application.services.transaction``:

- ``errors``        — ``TransactionApplicationError``
- ``validators``    — payload validation / primitive coercion
- ``mutations``     — create/update building blocks (ref auth, installment
                      builder, filter application, ``paid_at`` invariant)
- ``writes``        — full ``create`` / ``update`` execution paths
- ``list_queries``  — ``active`` / ``due`` list read paths
- ``query_helpers`` — ordering, update application, serialisation,
                      month-summary pagination
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, cast
from uuid import UUID

from app.application.services.transaction.errors import (
    TransactionApplicationError as TransactionApplicationError,  # re-export
)
from app.application.services.transaction.list_queries import (
    fetch_active_transactions,
    fetch_due_transactions,
)
from app.application.services.transaction.query_helpers import (
    _resolve_month_summary_page as _resolve_month_summary_page,  # re-export
)
from app.application.services.transaction.query_helpers import (
    _serialize_transaction as _serialize_transaction,  # re-export
)
from app.application.services.transaction.validators import (
    _parse_month as _parse_month,  # re-export
)
from app.application.services.transaction.writes import (
    execute_create_transaction,
    execute_update_transaction,
)
from app.extensions.database import db
from app.models.transaction import Transaction
from app.services.cache_service import get_cache_service
from app.services.transaction_analytics_service import TransactionAnalyticsService
from app.services.transaction_serialization import TransactionPayload

_TRANSACTION_NOT_FOUND_MESSAGE = "Transação não encontrada."


class TransactionLedgerService:
    """Handles CRUD, validations, and list queries for Transaction records."""

    def __init__(
        self,
        *,
        user_id: UUID,
        analytics_service_factory: Callable[[UUID], TransactionAnalyticsService],
    ) -> None:
        self._user_id = user_id
        self._analytics_service_factory = analytics_service_factory

    @classmethod
    def with_defaults(cls, user_id: UUID) -> TransactionLedgerService:
        return cls(
            user_id=user_id,
            analytics_service_factory=TransactionAnalyticsService,
        )

    def _invalidate_dashboard_cache(self) -> None:
        get_cache_service().invalidate_pattern(f"dashboard:overview:{self._user_id}:*")

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def create_transaction(
        self,
        payload: dict[str, Any],
        *,
        installment_amount_builder: Callable[[Any, int], list[Any]],
    ) -> dict[str, Any]:
        return execute_create_transaction(
            user_id=self._user_id,
            payload=payload,
            installment_amount_builder=installment_amount_builder,
            invalidate_cache=self._invalidate_dashboard_cache,
        )

    def update_transaction(
        self,
        transaction_id: UUID,
        payload: dict[str, Any],
    ) -> TransactionPayload:
        transaction = self._fetch_owned_transaction(
            transaction_id, forbidden_verb="editar"
        )
        return execute_update_transaction(
            user_id=self._user_id,
            transaction=transaction,
            payload=payload,
            invalidate_cache=self._invalidate_dashboard_cache,
        )

    def _series_members(self, transaction: Transaction) -> list[Transaction]:
        """Returns all owned, non-deleted rows of a recurring/installment series.

        The series key is resolved from ``recurrence_series_id`` (canonical),
        falling back to ``installment_group_id`` then the row id so it works for
        rows created before the backfill and for freshly-created templates.

        @param transaction Any member of the series.
        @return Owned, non-deleted transactions in the same series.
        """
        series_key = (
            transaction.recurrence_series_id
            or transaction.installment_group_id
            or transaction.id
        )
        return cast(
            "list[Transaction]",
            Transaction.query.filter(
                Transaction.user_id == self._user_id,
                Transaction.deleted.is_(False),
                db.or_(
                    Transaction.recurrence_series_id == series_key,
                    Transaction.installment_group_id == series_key,
                    Transaction.id == series_key,
                ),
            ).all(),
        )

    def delete_transaction(
        self, transaction_id: UUID, *, scope: str = "occurrence"
    ) -> None:
        """Soft-deletes a transaction, or its whole recurring series.

        @param transaction_id Target transaction id.
        @param scope ``"occurrence"`` (default) deletes only this row;
            ``"series"`` soft-deletes every occurrence sharing the series key.
        """
        transaction = self._fetch_owned_transaction(
            transaction_id, forbidden_verb="deletar"
        )

        targets = (
            self._series_members(transaction) if scope == "series" else [transaction]
        )

        try:
            from app.extensions.audit_trail import record_entity_delete

            for target in targets:
                target.deleted = True
                record_entity_delete(
                    entity_type="transaction",
                    entity_id=str(target.id),
                    actor_id=str(self._user_id),
                )
            db.session.commit()
            self._invalidate_dashboard_cache()
        except Exception:
            db.session.rollback()
            raise

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_transaction(self, transaction_id: UUID) -> TransactionPayload:
        return _serialize_transaction(
            self._fetch_owned_transaction(transaction_id, forbidden_verb="visualizar")
        )

    def get_active_transactions(
        self,
        *,
        page: int,
        per_page: int,
        transaction_type: str | None,
        status: str | None,
        start_date: date | None,
        end_date: date | None,
        tag_id: UUID | None,
        account_id: UUID | None,
        credit_card_id: UUID | None,
    ) -> dict[str, Any]:
        return fetch_active_transactions(
            user_id=self._user_id,
            page=page,
            per_page=per_page,
            transaction_type=transaction_type,
            status=status,
            start_date=start_date,
            end_date=end_date,
            tag_id=tag_id,
            account_id=account_id,
            credit_card_id=credit_card_id,
        )

    def get_due_transactions(
        self,
        *,
        start_date: str | date | None,
        end_date: str | date | None,
        page: int,
        per_page: int,
        order_by: str = "overdue_first",
    ) -> dict[str, Any]:
        return fetch_due_transactions(
            user_id=self._user_id,
            start_date=start_date,
            end_date=end_date,
            page=page,
            per_page=per_page,
            order_by=order_by,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_owned_transaction(
        self, transaction_id: UUID, *, forbidden_verb: str
    ) -> Transaction:
        """Load a non-deleted transaction owned by this user, or raise."""
        transaction = cast(
            Transaction | None,
            Transaction.query.filter_by(id=transaction_id, deleted=False).first(),
        )
        if transaction is None:
            raise TransactionApplicationError(
                message=_TRANSACTION_NOT_FOUND_MESSAGE,
                code="NOT_FOUND",
                status_code=404,
            )

        if str(transaction.user_id) != str(self._user_id):
            raise TransactionApplicationError(
                message=f"Você não tem permissão para {forbidden_verb} esta transação.",
                code="FORBIDDEN",
                status_code=403,
            )

        return transaction
