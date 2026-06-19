from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from sqlalchemy import case, func, literal

from app.extensions.database import db
from app.models.tag import Tag
from app.models.transaction import (
    Transaction,
    TransactionImpactPolicy,
    TransactionStatus,
    TransactionType,
)
from app.services.transaction_trends import (
    classify_survival as classify_survival,  # re-export
)
from app.services.transaction_trends import (
    compute_dashboard_trends,
    compute_survival_index,
)

if TYPE_CHECKING:
    from app.application.services.transaction.query_types import (
        SurvivalIndexResult,
        TransactionTrendsResult,
    )


class TransactionAnalyticsService:
    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id

    def _month_query(self, *, year: int, month_number: int) -> Any:
        return (
            Transaction.query.filter_by(user_id=self.user_id, deleted=False)
            .filter(Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY)
            .filter(db.extract("year", Transaction.due_date) == year)
            .filter(db.extract("month", Transaction.due_date) == month_number)
        )

    def get_month_transactions(
        self, *, year: int, month_number: int
    ) -> list[Transaction]:
        transactions = self._month_query(year=year, month_number=month_number).all()
        return cast(list[Transaction], transactions)

    def get_month_transaction_count(self, *, year: int, month_number: int) -> int:
        total = self._month_query(year=year, month_number=month_number).count()
        return int(total)

    def get_month_transactions_page(
        self,
        *,
        year: int,
        month_number: int,
        page: int,
        per_page: int,
    ) -> list[Transaction]:
        transactions = (
            self._month_query(year=year, month_number=month_number)
            .order_by(Transaction.created_at.asc(), Transaction.id.asc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return cast(list[Transaction], transactions)

    def get_month_aggregates(self, *, year: int, month_number: int) -> dict[str, Any]:
        row = (
            db.session.query(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Transaction.type == TransactionType.INCOME,
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("income_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Transaction.type == TransactionType.EXPENSE,
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("expense_total"),
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
            )
            .filter(Transaction.user_id == self.user_id)
            .filter(Transaction.deleted.is_(False))
            .filter(Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY)
            .filter(db.extract("year", Transaction.due_date) == year)
            .filter(db.extract("month", Transaction.due_date) == month_number)
            .one()
        )

        income_total = row.income_total or 0
        expense_total = row.expense_total or 0
        return {
            "income_total": income_total,
            "expense_total": expense_total,
            "balance": income_total - expense_total,
            "total_transactions": int(row.total_transactions or 0),
            "income_transactions": int(row.income_transactions or 0),
            "expense_transactions": int(row.expense_transactions or 0),
        }

    def get_status_counts(self, *, year: int, month_number: int) -> dict[str, int]:
        default_counts = {
            "paid": 0,
            "pending": 0,
            "cancelled": 0,
            "postponed": 0,
            "overdue": 0,
        }
        rows = (
            db.session.query(Transaction.status, func.count(Transaction.id))
            .filter(Transaction.user_id == self.user_id)
            .filter(Transaction.deleted.is_(False))
            .filter(Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY)
            .filter(db.extract("year", Transaction.due_date) == year)
            .filter(db.extract("month", Transaction.due_date) == month_number)
            .group_by(Transaction.status)
            .all()
        )
        for status_enum, count in rows:
            default_counts[status_enum.value] = int(count)
        return default_counts

    def get_top_categories(
        self,
        *,
        year: int,
        month_number: int,
        transaction_type: TransactionType,
    ) -> list[dict[str, Any]]:
        rows = (
            db.session.query(
                Transaction.tag_id,
                Tag.name,
                func.coalesce(func.sum(Transaction.amount), 0).label("total_amount"),
                func.count(Transaction.id).label("transactions_count"),
            )
            .outerjoin(Tag, Tag.id == Transaction.tag_id)
            .filter(Transaction.user_id == self.user_id)
            .filter(Transaction.deleted.is_(False))
            .filter(Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY)
            .filter(Transaction.type == transaction_type)
            .filter(db.extract("year", Transaction.due_date) == year)
            .filter(db.extract("month", Transaction.due_date) == month_number)
            .group_by(Transaction.tag_id, Tag.name)
            .order_by(func.sum(Transaction.amount).desc())
            .limit(5)
            .all()
        )

        return [
            {
                "tag_id": str(tag_id) if tag_id else None,
                "category_name": tag_name or "Sem categoria",
                "total_amount": float(total_amount),
                "transactions_count": int(transactions_count),
            }
            for tag_id, tag_name, total_amount, transactions_count in rows
        ]

    def get_dashboard_overview_coalesced(
        self, *, year: int, month_number: int
    ) -> dict[str, Any]:
        """Coalesce aggregates + status into 1 SQL query (down from 2).

        PERF: antes get_month_aggregates + get_status_counts emitiam 2
        queries separadas. Este metodo combina ambos em uma unica passagem
        via CASE/conditional aggregation.

        Usado por get_month_dashboard junto com get_top_categories_both
        para reduzir o total do dashboard de 4 queries para 2.
        """
        _base = (
            Transaction.user_id == self.user_id,
            Transaction.deleted.is_(False),
            Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY,
            db.extract("year", Transaction.due_date) == year,
            db.extract("month", Transaction.due_date) == month_number,
        )

        row = (
            db.session.query(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Transaction.type == TransactionType.INCOME,
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("income_total"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Transaction.type == TransactionType.EXPENSE,
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("expense_total"),
                func.count(Transaction.id).label("total_transactions"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.type == TransactionType.INCOME, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("income_transactions"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.type == TransactionType.EXPENSE, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("expense_transactions"),
                func.coalesce(
                    func.sum(
                        case((Transaction.status == TransactionStatus.PAID, 1), else_=0)
                    ),
                    0,
                ).label("status_paid"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.status == TransactionStatus.PENDING, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("status_pending"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.status == TransactionStatus.CANCELLED, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("status_cancelled"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.status == TransactionStatus.POSTPONED, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("status_postponed"),
                func.coalesce(
                    func.sum(
                        case(
                            (Transaction.status == TransactionStatus.OVERDUE, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("status_overdue"),
            )
            .filter(*_base)
            .one()
        )

        income_total = row.income_total or 0
        expense_total = row.expense_total or 0

        return {
            "income_total": income_total,
            "expense_total": expense_total,
            "balance": income_total - expense_total,
            "total_transactions": int(row.total_transactions or 0),
            "income_transactions": int(row.income_transactions or 0),
            "expense_transactions": int(row.expense_transactions or 0),
            "status": {
                "paid": int(row.status_paid or 0),
                "pending": int(row.status_pending or 0),
                "cancelled": int(row.status_cancelled or 0),
                "postponed": int(row.status_postponed or 0),
                "overdue": int(row.status_overdue or 0),
            },
        }

    def get_top_categories_both(
        self,
        *,
        year: int,
        month_number: int,
        limit: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return top-categories for INCOME and EXPENSE in a UNION ALL query.

        PERF: replaces two get_top_categories calls with a single query
        that fetches both sets in one round-trip to the database.
        """
        _common = (
            Transaction.user_id == self.user_id,
            Transaction.deleted.is_(False),
            Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY,
            db.extract("year", Transaction.due_date) == year,
            db.extract("month", Transaction.due_date) == month_number,
        )

        def _subq(tx_type: TransactionType) -> Any:
            label = "income" if tx_type == TransactionType.INCOME else "expense"
            return (
                db.session.query(
                    Transaction.tag_id,
                    Tag.name.label("tag_name"),
                    func.coalesce(func.sum(Transaction.amount), 0).label(
                        "total_amount"
                    ),
                    func.count(Transaction.id).label("transactions_count"),
                    literal(label).label("tx_type"),
                )
                .outerjoin(Tag, Tag.id == Transaction.tag_id)
                .filter(*_common)
                .filter(Transaction.type == tx_type)
                .group_by(Transaction.tag_id, Tag.name)
                .order_by(func.sum(Transaction.amount).desc())
                .limit(limit)
                .subquery()
            )

        exp_sub = _subq(TransactionType.EXPENSE)
        inc_sub = _subq(TransactionType.INCOME)

        rows = (
            db.session.query(
                exp_sub.c.tag_id,
                exp_sub.c.tag_name,
                exp_sub.c.total_amount,
                exp_sub.c.transactions_count,
                exp_sub.c.tx_type,
            )
            .union_all(
                db.session.query(
                    inc_sub.c.tag_id,
                    inc_sub.c.tag_name,
                    inc_sub.c.total_amount,
                    inc_sub.c.transactions_count,
                    inc_sub.c.tx_type,
                )
            )
            .all()
        )

        expense_categories: list[dict[str, Any]] = []
        income_categories: list[dict[str, Any]] = []
        for tag_id, tag_name, total_amount, transactions_count, tx_type in rows:
            entry: dict[str, Any] = {
                "tag_id": str(tag_id) if tag_id else None,
                "category_name": tag_name or "Sem categoria",
                "total_amount": float(total_amount),
                "transactions_count": int(transactions_count),
            }
            if tx_type == "expense":
                expense_categories.append(entry)
            else:
                income_categories.append(entry)

        return {
            "top_expense_categories": expense_categories,
            "top_income_categories": income_categories,
        }

    def get_dashboard_trends(self, *, months: int) -> TransactionTrendsResult:
        return compute_dashboard_trends(user_id=self.user_id, months=months)

    def get_survival_index(self, *, period_months: int = 3) -> SurvivalIndexResult:
        return compute_survival_index(user_id=self.user_id, period_months=period_months)


__all__ = [
    "TransactionAnalyticsService",
    "classify_survival",
]
