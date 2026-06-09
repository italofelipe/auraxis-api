from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from marshmallow import ValidationError
from sqlalchemy import extract, func
from sqlalchemy.orm import joinedload

from app.extensions.database import db
from app.models.budget import Budget
from app.models.tag import Tag
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.schemas.budget_schema import BudgetSchema


@dataclass
class BudgetServiceError(Exception):
    message: str
    code: str
    status_code: int
    details: dict[str, Any] | None = None


class BudgetService:
    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        self._schema = BudgetSchema()
        self._partial_schema = BudgetSchema(partial=True)

    def create_budget(self, payload: dict[str, Any]) -> Budget:
        try:
            validated = self._schema.load(payload)
        except ValidationError as exc:
            raise BudgetServiceError(
                message="Dados inválidos para orçamento.",
                code="VALIDATION_ERROR",
                status_code=400,
                details={"messages": exc.messages},
            ) from exc

        self._validate_tag_ownership(validated.get("tag_id"))

        budget = Budget(user_id=self.user_id, **validated)
        db.session.add(budget)
        db.session.commit()
        return budget

    def list_budgets(self, *, active_only: bool = True) -> list[Budget]:
        # joinedload(Budget.tag) prevents N+1: serialize() accesses budget.tag.name
        # and budget.tag.color for every budget in the list, so we load the
        # relationship eagerly in a single JOIN instead of one query per budget.
        query = Budget.query.options(joinedload(Budget.tag)).filter_by(  # type: ignore[arg-type]
            user_id=self.user_id
        )
        if active_only:
            query = query.filter_by(is_active=True)
        return cast(list[Budget], query.order_by(Budget.created_at.desc()).all())

    def get_budget(self, budget_id: UUID) -> Budget:
        budget = cast(Budget | None, Budget.query.filter_by(id=budget_id).first())
        if budget is None:
            raise BudgetServiceError(
                message="Orçamento não encontrado.",
                code="NOT_FOUND",
                status_code=404,
            )
        if str(budget.user_id) != str(self.user_id):
            raise BudgetServiceError(
                message="Você não tem permissão para acessar este orçamento.",
                code="FORBIDDEN",
                status_code=403,
            )
        return budget

    def update_budget(self, budget_id: UUID, payload: dict[str, Any]) -> Budget:
        budget = self.get_budget(budget_id)
        try:
            validated = self._partial_schema.load(payload, partial=True)
        except ValidationError as exc:
            raise BudgetServiceError(
                message="Dados inválidos para atualização do orçamento.",
                code="VALIDATION_ERROR",
                status_code=400,
                details={"messages": exc.messages},
            ) from exc

        if "tag_id" in validated:
            self._validate_tag_ownership(validated["tag_id"])

        for field, value in validated.items():
            setattr(budget, field, value)
        db.session.commit()
        return budget

    def delete_budget(self, budget_id: UUID) -> None:
        budget = self.get_budget(budget_id)
        db.session.delete(budget)
        db.session.commit()

    def get_spent_for_budget(self, budget: Budget) -> Decimal:
        """
        Calculates the total spent amount for a given budget in its current period.

        - monthly: sums committed expense transactions for the current calendar
          month filtered by category/tag_id (or all if both are null).
        - weekly: sums committed expense transactions for the current ISO week.
        - custom: sums committed expense transactions between start_date and
          end_date.
        """
        today = date.today()
        committed_statuses = (
            TransactionStatus.PAID,
            TransactionStatus.PENDING,
            TransactionStatus.OVERDUE,
        )

        query = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.user_id == self.user_id,
            Transaction.type == TransactionType.EXPENSE,
            Transaction.status.in_(committed_statuses),
            Transaction.deleted.is_(False),
        )

        if budget.category is not None:
            # Filter by structured category field (preferred over tag_id)
            from app.models.transaction import TransactionCategory

            query = query.filter(
                Transaction.category == TransactionCategory(budget.category)
            )
        elif budget.tag_id is not None:
            # Legacy: fall back to tag_id filtering for budgets not yet migrated
            query = query.filter(Transaction.tag_id == budget.tag_id)

        if budget.period == "monthly":
            query = query.filter(
                extract("year", Transaction.due_date) == today.year,
                extract("month", Transaction.due_date) == today.month,
            )
        elif budget.period == "weekly":
            # ISO week: Monday to Sunday
            monday = today - __import__("datetime").timedelta(days=today.weekday())
            sunday = monday + __import__("datetime").timedelta(days=6)
            query = query.filter(
                Transaction.due_date >= monday,
                Transaction.due_date <= sunday,
            )
        elif budget.period == "custom" and budget.start_date and budget.end_date:
            query = query.filter(
                Transaction.due_date >= budget.start_date,
                Transaction.due_date <= budget.end_date,
            )

        result = query.scalar()
        return Decimal(str(result)) if result is not None else Decimal("0")

    def serialize(self, budget: Budget) -> dict[str, Any]:
        data = cast(dict[str, Any], self._schema.dump(budget))
        # Enrich with tag info
        tag_name = None
        tag_color = None
        if budget.tag is not None:
            tag_name = budget.tag.name
            tag_color = budget.tag.color
        data["tag_name"] = tag_name
        data["tag_color"] = tag_color
        return data

    def serialize_with_spent(self, budget: Budget) -> dict[str, Any]:
        data = self.serialize(budget)
        amount = Decimal(str(budget.amount))
        spent = self.get_spent_for_budget(budget)
        remaining = amount - spent
        percentage_used = float(spent / amount * 100) if amount > 0 else 0.0
        data["spent"] = str(spent)
        data["remaining"] = str(remaining)
        data["percentage_used"] = round(percentage_used, 2)
        data["is_over_budget"] = spent > amount
        return data

    def get_summary(self) -> dict[str, Any]:
        """Returns total budgeted vs total spent for current period (active budgets)."""
        budgets = self.list_budgets(active_only=True)
        total_budgeted = Decimal("0")
        total_spent = Decimal("0")
        for budget in budgets:
            total_budgeted += Decimal(str(budget.amount))
            total_spent += self.get_spent_for_budget(budget)
        total_remaining = total_budgeted - total_spent
        return {
            "total_budgeted": str(total_budgeted),
            "total_spent": str(total_spent),
            "total_remaining": str(total_remaining),
            "percentage_used": (
                round(float(total_spent / total_budgeted * 100), 2)
                if total_budgeted > 0
                else 0.0
            ),
            "budget_count": len(budgets),
        }

    # --- private helpers ---

    def _validate_tag_ownership(self, tag_id: UUID | None) -> None:
        if tag_id is None:
            return
        tag = cast(Tag | None, Tag.query.filter_by(id=tag_id).first())
        if tag is None or str(tag.user_id) != str(self.user_id):
            raise BudgetServiceError(
                message="Tag não encontrada ou não pertence ao usuário.",
                code="TAG_NOT_FOUND",
                status_code=404,
            )
