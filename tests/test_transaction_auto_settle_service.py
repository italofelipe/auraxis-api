from datetime import date
from decimal import Decimal

from app.extensions.database import db
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.services.transaction_auto_settle_service import TransactionAutoSettleService

TODAY = date(2026, 6, 29)


def _create_user() -> User:
    user = User(name="settle-user", email="settle-user@email.com", password="x")
    db.session.add(user)
    db.session.commit()
    return user


def _make_transaction(
    user_id: object,
    *,
    title: str,
    due_date: date,
    status: TransactionStatus = TransactionStatus.PENDING,
    auto_settle: bool = True,
) -> Transaction:
    transaction = Transaction(
        user_id=user_id,
        title=title,
        amount=Decimal("100.00"),
        type=TransactionType.INCOME,
        status=status,
        due_date=due_date,
        auto_settle=auto_settle,
        currency="BRL",
    )
    db.session.add(transaction)
    db.session.commit()
    return transaction


def test_settles_due_opted_in_open_transactions(app) -> None:
    with app.app_context():
        user = _create_user()
        due = _make_transaction(user.id, title="Salário", due_date=date(2026, 6, 1))
        postponed = _make_transaction(
            user.id,
            title="Adiantamento",
            due_date=date(2026, 5, 10),
            status=TransactionStatus.POSTPONED,
        )

        settled = TransactionAutoSettleService.settle_due(reference_date=TODAY)

        assert settled == 2
        db.session.refresh(due)
        db.session.refresh(postponed)
        assert due.status == TransactionStatus.PAID
        assert due.paid_at is not None
        assert postponed.status == TransactionStatus.PAID


def test_does_not_settle_future_or_non_opted_or_closed(app) -> None:
    with app.app_context():
        user = _create_user()
        future = _make_transaction(user.id, title="Futuro", due_date=date(2026, 7, 15))
        not_opted = _make_transaction(
            user.id, title="Manual", due_date=date(2026, 6, 1), auto_settle=False
        )
        already_paid = _make_transaction(
            user.id,
            title="Pago",
            due_date=date(2026, 6, 1),
            status=TransactionStatus.PAID,
        )

        settled = TransactionAutoSettleService.settle_due(reference_date=TODAY)

        assert settled == 0
        db.session.refresh(future)
        db.session.refresh(not_opted)
        db.session.refresh(already_paid)
        assert future.status == TransactionStatus.PENDING
        assert not_opted.status == TransactionStatus.PENDING
        assert already_paid.paid_at is None


def test_settle_due_is_idempotent(app) -> None:
    with app.app_context():
        user = _create_user()
        _make_transaction(user.id, title="Salário", due_date=date(2026, 6, 1))

        first = TransactionAutoSettleService.settle_due(reference_date=TODAY)
        second = TransactionAutoSettleService.settle_due(reference_date=TODAY)

        assert first == 1
        assert second == 0


def test_count_due_does_not_mutate(app) -> None:
    with app.app_context():
        user = _create_user()
        tx = _make_transaction(user.id, title="Salário", due_date=date(2026, 6, 1))

        count = TransactionAutoSettleService.count_due(reference_date=TODAY)

        assert count == 1
        db.session.refresh(tx)
        assert tx.status == TransactionStatus.PENDING
