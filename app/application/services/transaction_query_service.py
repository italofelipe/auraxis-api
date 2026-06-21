"""Transaction Query Service — read-side facade.

Composes the transaction application service (CRUD + month aggregates) and
the analytics service (multi-month trends / runway) behind a single
query-oriented API used by REST + GraphQL resolvers.

Type payloads live in ``app.application.services.transaction.query_types``;
multi-month / survival aggregation logic lives on
``TransactionAnalyticsService``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID

from sqlalchemy import case, func

from app.application.services.transaction.query_types import (
    SurvivalClassification,
    SurvivalIndexResult,
    TransactionCountsPayload,
    TransactionDashboardResult,
    TransactionDueRangeResult,
    TransactionExpensePeriodResult,
    TransactionListResult,
    TransactionPaginationPayload,
    TransactionQueryDependencies,
    TransactionSummaryResult,
    TransactionTrendsMonthEntry,
    TransactionTrendsResult,
    WeeklySummaryResult,
)
from app.application.services.transaction_application_service import (
    TransactionApplicationService,
)
from app.extensions.database import db
from app.models.transaction import Transaction, TransactionType
from app.services.credit_card_bill_service import (
    build_competence_month_filter,
    month_span_if_full_calendar_month,
)
from app.services.transaction_analytics_service import (
    TransactionAnalyticsService,
)
from app.services.transaction_analytics_service import (
    classify_survival as _classify_survival,  # re-exported for back-compat
)
from app.services.transaction_serialization import (
    TransactionPayload,
    serialize_transaction_payload,
)


class TransactionQueryService:
    def __init__(
        self,
        *,
        user_id: UUID,
        dependencies: TransactionQueryDependencies,
    ) -> None:
        self._user_id = user_id
        self._dependencies = dependencies

    @classmethod
    def with_defaults(cls, user_id: UUID) -> TransactionQueryService:
        return cls(
            user_id=user_id,
            dependencies=TransactionQueryDependencies(
                transaction_application_service_factory=(
                    TransactionApplicationService.with_defaults
                ),
                analytics_service_factory=TransactionAnalyticsService,
            ),
        )

    def get_transaction(self, transaction_id: UUID) -> TransactionPayload:
        return self._application_service().get_transaction(transaction_id)

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
    ) -> TransactionListResult:
        return cast(
            TransactionListResult,
            self._application_service().get_active_transactions(
                page=page,
                per_page=per_page,
                transaction_type=transaction_type,
                status=status,
                start_date=start_date,
                end_date=end_date,
                tag_id=tag_id,
                account_id=account_id,
                credit_card_id=credit_card_id,
            ),
        )

    def get_month_summary(
        self,
        *,
        month: str,
        page: int,
        per_page: int,
    ) -> TransactionSummaryResult:
        return cast(
            TransactionSummaryResult,
            self._application_service().get_month_summary(
                month=month,
                page=page,
                page_size=per_page,
            ),
        )

    def get_dashboard_overview(self, *, month: str) -> TransactionDashboardResult:
        return cast(
            TransactionDashboardResult,
            self._application_service().get_month_dashboard(month=month),
        )

    def get_dashboard_trends(self, *, months: int) -> TransactionTrendsResult:
        return self._analytics_service().get_dashboard_trends(months=months)

    def get_due_transactions(
        self,
        *,
        start_date: str | date | None,
        end_date: str | date | None,
        page: int,
        per_page: int,
        order_by: str,
    ) -> TransactionDueRangeResult:
        return cast(
            TransactionDueRangeResult,
            self._application_service().get_due_transactions(
                start_date=start_date,
                end_date=end_date,
                page=page,
                per_page=per_page,
                order_by=order_by,
            ),
        )

    def get_expense_period(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        page: int,
        per_page: int,
        ordering_clause: Any,
    ) -> TransactionExpensePeriodResult:
        base_query = self._build_period_query(
            start_date=start_date,
            end_date=end_date,
        )
        total_transactions, income_transactions, expense_transactions = (
            self._build_period_counts(
                start_date=start_date,
                end_date=end_date,
            )
        )

        expenses_query = base_query.filter(Transaction.type == TransactionType.EXPENSE)
        total_expenses = expense_transactions
        pages = (total_expenses + per_page - 1) // per_page if total_expenses else 0
        expenses = (
            expenses_query.order_by(ordering_clause)
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return {
            "expenses": [serialize_transaction_payload(item) for item in expenses],
            "counts": {
                "total_transactions": total_transactions,
                "income_transactions": income_transactions,
                "expense_transactions": expense_transactions,
            },
            "pagination": {
                "total": total_expenses,
                "page": page,
                "per_page": per_page,
                "pages": pages,
            },
        }

    def list_deleted_transactions(self) -> list[TransactionPayload]:
        deleted_transactions = Transaction.query.filter_by(
            user_id=self._user_id,
            deleted=True,
        ).all()
        return [serialize_transaction_payload(item) for item in deleted_transactions]

    def get_survival_index(self, *, period_months: int = 3) -> SurvivalIndexResult:
        return self._analytics_service().get_survival_index(period_months=period_months)

    def get_weekly_summary(
        self,
        *,
        period: str = "1m",
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> WeeklySummaryResult:
        from app.services.weekly_summary import compute_weekly_summary

        return compute_weekly_summary(
            user_id=self._user_id,
            period=period,
            start_date=start_date,
            end_date=end_date,
        )

    def _apply_period_date_filter(
        self,
        query: Any,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> Any:
        """Apply the period date filter, switching to competence-month grouping.

        When ``[start_date, end_date]`` spans exactly one calendar month, the
        raw ``due_date`` range is replaced by a competence-month filter so
        credit-card transactions are grouped by their bill cycle (matching the
        Cartões/fatura view). Custom/partial ranges keep the raw ``due_date``
        filter. Applied identically to the items and counts queries so totals
        and pagination stay consistent.
        """
        competence_month = month_span_if_full_calendar_month(start_date, end_date)
        if competence_month is not None:
            return query.filter(
                build_competence_month_filter(self._user_id, competence_month)
            )
        if start_date is not None:
            query = query.filter(Transaction.due_date >= start_date)
        if end_date is not None:
            query = query.filter(Transaction.due_date <= end_date)
        return query

    def _build_period_query(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> Any:
        query = Transaction.query.filter_by(user_id=self._user_id, deleted=False)
        return self._apply_period_date_filter(
            query, start_date=start_date, end_date=end_date
        )

    def _build_period_counts(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[int, int, int]:
        counts_query = db.session.query(
            func.count(Transaction.id).label("total_transactions"),
            func.coalesce(
                func.sum(
                    case((Transaction.type == TransactionType.INCOME, 1), else_=0)
                ),
                0,
            ).label("income_transactions"),
            func.coalesce(
                func.sum(
                    case((Transaction.type == TransactionType.EXPENSE, 1), else_=0)
                ),
                0,
            ).label("expense_transactions"),
        ).filter(Transaction.user_id == self._user_id, Transaction.deleted.is_(False))
        counts_query = self._apply_period_date_filter(
            counts_query, start_date=start_date, end_date=end_date
        )
        row = counts_query.one()
        return (
            int(row.total_transactions or 0),
            int(row.income_transactions or 0),
            int(row.expense_transactions or 0),
        )

    def _application_service(self) -> TransactionApplicationService:
        return self._dependencies.transaction_application_service_factory(self._user_id)

    def _analytics_service(self) -> TransactionAnalyticsService:
        return self._dependencies.analytics_service_factory(self._user_id)


__all__ = [
    "SurvivalClassification",
    "SurvivalIndexResult",
    "TransactionCountsPayload",
    "TransactionDashboardResult",
    "TransactionDueRangeResult",
    "TransactionExpensePeriodResult",
    "TransactionListResult",
    "TransactionPaginationPayload",
    "TransactionQueryDependencies",
    "TransactionQueryService",
    "TransactionSummaryResult",
    "TransactionTrendsMonthEntry",
    "TransactionTrendsResult",
    "_classify_survival",
]
