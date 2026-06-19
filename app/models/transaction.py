# mypy: disable-error-code=name-defined

import enum
from typing import Any
from uuid import UUID as UUIDType
from uuid import uuid4

from sqlalchemy.dialects.postgresql import UUID

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive


class TransactionType(enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"


class TransactionCategory(enum.Enum):
    """Structured category for budget tracking — separate from free-form tags."""

    alimentacao = "alimentacao"
    transporte = "transporte"
    moradia = "moradia"
    saude = "saude"
    lazer = "lazer"
    educacao = "educacao"
    investimentos = "investimentos"
    poupanca = "poupanca"
    outros = "outros"


class TransactionStatus(enum.Enum):
    PAID = "paid"
    PENDING = "pending"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"
    OVERDUE = "overdue"


class TransactionImpactPolicy(enum.Enum):
    FULL = "full"
    CARDS_ONLY = "cards_only"
    PLANNED_UNTIL_BILL = "planned_until_bill"


class RecurrenceUnit(enum.Enum):
    """Cadence unit for a recurring transaction (combined with an interval)."""

    day = "day"
    week = "week"
    month = "month"
    year = "year"


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)

    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(300))
    observation = db.Column(db.String(500))
    is_recurring = db.Column(db.Boolean, default=False)
    is_installment = db.Column(db.Boolean, default=False)
    installment_count = db.Column(db.Integer, nullable=True)
    # Recurrence cadence: repeat every ``recurrence_interval`` ``recurrence_unit``s
    # (e.g. interval=2 + unit=week → every two weeks). Legacy rows default to a
    # monthly cadence so existing recurring transactions keep working.
    recurrence_interval = db.Column(
        db.Integer, nullable=False, default=1, server_default=db.text("1")
    )
    recurrence_unit = db.Column(
        db.Enum(
            RecurrenceUnit,
            name="recurrence_unit_enum",
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=RecurrenceUnit.month,
        server_default=RecurrenceUnit.month.value,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    currency = db.Column(db.String(3), default="BRL")

    status = db.Column(db.Enum(TransactionStatus), default=TransactionStatus.PENDING)
    type = db.Column(db.Enum(TransactionType), nullable=False)

    due_date = db.Column(db.Date, nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    category = db.Column(
        db.Enum(
            TransactionCategory,
            name="transaction_category_enum",
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    tag_id = db.Column(UUID(as_uuid=True), db.ForeignKey("tags.id"), nullable=True)
    account_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("accounts.id"), nullable=True
    )
    credit_card_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("credit_cards.id"), nullable=True
    )
    impact_policy = db.Column(
        db.Enum(
            TransactionImpactPolicy,
            name="transaction_impact_policy_enum",
            native_enum=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=TransactionImpactPolicy.FULL,
        server_default=TransactionImpactPolicy.FULL.value,
    )
    installment_group_id = db.Column(UUID(as_uuid=True), nullable=True)
    # Links all occurrences of one recurring series so a user can delete a
    # single occurrence or the whole series. Backfilled from
    # ``coalesce(installment_group_id, id)`` for legacy recurring rows.
    recurrence_series_id = db.Column(UUID(as_uuid=True), nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    source = db.Column(
        db.String(40),
        nullable=False,
        default="manual",
        server_default="manual",
    )
    external_id = db.Column(db.String(120), nullable=True)
    bank_name = db.Column(db.String(80), nullable=True)

    deleted = db.Column(
        db.Boolean, default=False, nullable=False, server_default=db.text("false")
    )

    created_at = db.Column(db.DateTime, default=utc_now_naive)
    updated_at = db.Column(db.DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    tag = db.relationship("Tag", backref="transactions")
    account = db.relationship("Account", backref="transactions")
    credit_card = db.relationship("CreditCard", backref="transactions")

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "external_id", name="uq_transactions_user_external_id"
        ),
        db.Index("ix_transactions_user_source", "user_id", "source"),
        # PERF-GAP-01: composite indexes for hot list/filter/date-range queries.
        db.Index("ix_transactions_user_deleted", "user_id", "deleted"),
        db.Index(
            "ix_transactions_user_deleted_due_date", "user_id", "deleted", "due_date"
        ),
        # Series lookups for "delete whole recurring series".
        db.Index(
            "ix_transactions_user_recurrence_series",
            "user_id",
            "recurrence_series_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Transaction(id={self.id}, title={self.title}, amount={self.amount}, "
            f"status={self.status})>"
        )

    @staticmethod
    def get_monthly_summary(user_id: UUIDType, year: int, month: int) -> dict[str, Any]:
        from sqlalchemy import extract, func

        income_total = (
            db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter_by(user_id=user_id, deleted=False, type=TransactionType.INCOME)
            .filter(Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY)
            .filter(extract("year", Transaction.due_date) == year)
            .filter(extract("month", Transaction.due_date) == month)
            .scalar()
        )

        expense_total = (
            db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
            .filter_by(user_id=user_id, deleted=False, type=TransactionType.EXPENSE)
            .filter(Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY)
            .filter(extract("year", Transaction.due_date) == year)
            .filter(extract("month", Transaction.due_date) == month)
            .scalar()
        )

        transactions = (
            Transaction.query.filter_by(user_id=user_id, deleted=False)
            .filter(Transaction.impact_policy != TransactionImpactPolicy.CARDS_ONLY)
            .filter(extract("year", Transaction.due_date) == year)
            .filter(extract("month", Transaction.due_date) == month)
            .all()
        )

        return {
            "income_total": str(income_total),
            "expense_total": str(expense_total),
            "transactions": transactions,
        }
