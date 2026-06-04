"""Delete-scope tests for recurring transactions (#1444).

DELETE /transactions/{id}?scope=series must soft-delete every occurrence of a
recurring series, while the default (occurrence) only removes the single row.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from app.application.services.transaction_application_service import (
    TransactionApplicationService,
)
from app.extensions.database import db
from app.models.transaction import Transaction, TransactionType


def _make_occurrence(user_id: UUID, series_id: UUID, due: date) -> Transaction:
    return Transaction(
        user_id=user_id,
        title="Ações da microsoft",
        amount=Decimal("3120.00"),
        type=TransactionType.INCOME,
        due_date=due,
        is_recurring=True,
        installment_group_id=series_id,
        recurrence_series_id=series_id,
    )


def _active_count(user_id: UUID) -> int:
    return Transaction.query.filter_by(user_id=user_id, deleted=False).count()


def test_scope_series_soft_deletes_all_occurrences(app: object) -> None:
    with app.app_context():  # type: ignore[attr-defined]
        user_id = uuid4()
        series_id = uuid4()
        rows = [
            _make_occurrence(user_id, series_id, date(2026, 6, 3)),
            _make_occurrence(user_id, series_id, date(2026, 7, 3)),
            _make_occurrence(user_id, series_id, date(2026, 8, 3)),
        ]
        db.session.add_all(rows)
        db.session.commit()
        assert _active_count(user_id) == 3

        service = TransactionApplicationService.with_defaults(user_id)
        service.delete_transaction(rows[1].id, scope="series")

        assert _active_count(user_id) == 0


def test_scope_occurrence_deletes_only_the_target(app: object) -> None:
    with app.app_context():  # type: ignore[attr-defined]
        user_id = uuid4()
        series_id = uuid4()
        rows = [
            _make_occurrence(user_id, series_id, date(2026, 6, 3)),
            _make_occurrence(user_id, series_id, date(2026, 7, 3)),
        ]
        db.session.add_all(rows)
        db.session.commit()

        service = TransactionApplicationService.with_defaults(user_id)
        service.delete_transaction(rows[0].id)  # default scope=occurrence

        assert _active_count(user_id) == 1
        assert db.session.get(Transaction, rows[0].id).deleted is True
        assert db.session.get(Transaction, rows[1].id).deleted is False


def test_series_delete_does_not_touch_other_users(app: object) -> None:
    with app.app_context():  # type: ignore[attr-defined]
        user_id = uuid4()
        other_id = uuid4()
        series_id = uuid4()
        mine = _make_occurrence(user_id, series_id, date(2026, 6, 3))
        # Same series id value but a different owner must be untouched.
        theirs = _make_occurrence(other_id, series_id, date(2026, 6, 3))
        db.session.add_all([mine, theirs])
        db.session.commit()

        TransactionApplicationService.with_defaults(user_id).delete_transaction(
            mine.id, scope="series"
        )

        assert db.session.get(Transaction, mine.id).deleted is True
        assert db.session.get(Transaction, theirs.id).deleted is False
