from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.extensions.database import db
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.services.email_provider import get_email_outbox
from app.services.entitlement_service import activate_premium


def test_dispatch_due_soon_sends_reminders(app) -> None:
    today = date(2030, 6, 15)
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="CLI Test User",
            email="cli-test@email.com",
            password="hash",
        )
        db.session.add(user)
        db.session.flush()
        activate_premium(user.id, expires_at=None)

        tx_7 = Transaction(
            user_id=user.id,
            title="Aluguel",
            amount=Decimal("1500.00"),
            type=TransactionType.EXPENSE,
            status=TransactionStatus.PENDING,
            due_date=today + timedelta(days=7),
        )
        tx_1 = Transaction(
            user_id=user.id,
            title="Internet",
            amount=Decimal("99.90"),
            type=TransactionType.EXPENSE,
            status=TransactionStatus.PENDING,
            due_date=today + timedelta(days=1),
        )
        db.session.add_all([tx_7, tx_1])
        db.session.commit()

        runner = app.test_cli_runner()
        # Patch today so the CLI picks up the right window.
        # The service uses date.today() internally, so we monkeypatch it.
        import unittest.mock as mock

        with mock.patch(
            "app.application.services.transaction_reminder_service.date"
        ) as mock_date:
            mock_date.today.return_value = today
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = runner.invoke(args=["reminders", "dispatch-due-soon"])

        assert result.exit_code == 0
        assert "7-day reminders:" in result.output
        assert "1-day reminders:" in result.output
        assert "sent=1" in result.output

        outbox = get_email_outbox()
        assert len(outbox) >= 1


def test_dispatch_due_soon_email_provider_error_queues_to_dlq_and_exits_zero(
    app,
) -> None:
    """EmailProviderError is caught by the service, pushed to DLQ, and the CLI
    exits 0 with queued=N in output — the job is not considered failed."""
    import unittest.mock as mock

    from app.services.email_provider import EmailProviderError

    with app.app_context():
        runner = app.test_cli_runner()
        with (
            mock.patch(
                "app.application.services.transaction_reminder_service.get_default_email_provider"
            ) as mock_provider_factory,
            mock.patch(
                "app.application.services.transaction_reminder_service.get_email_dlq"
            ) as mock_dlq_factory,
        ):
            mock_provider = mock.MagicMock()
            mock_provider.send.side_effect = EmailProviderError(
                "RESEND_API_KEY missing"
            )
            mock_provider_factory.return_value = mock_provider

            mock_dlq = mock.MagicMock()
            mock_dlq_factory.return_value = mock_dlq

            user = User(
                id=uuid.uuid4(),
                name="Error Test User",
                email="error@email.com",
                password="hash",
            )
            db.session.add(user)
            db.session.flush()
            activate_premium(user.id, expires_at=None)
            tx = Transaction(
                user_id=user.id,
                title="Conta teste",
                amount=Decimal("50.00"),
                type=TransactionType.EXPENSE,
                status=TransactionStatus.PENDING,
                due_date=date.today() + timedelta(days=7),
            )
            db.session.add(tx)
            db.session.commit()

            result = runner.invoke(args=["reminders", "dispatch-due-soon"])

    assert result.exit_code == 0
    assert "queued=1" in result.output
    mock_dlq.push.assert_called_once()


def test_dispatch_due_soon_unexpected_error_exits_nonzero(app) -> None:
    """If dispatch raises an unexpected exception the CLI exits 1 and logs to stderr."""
    import unittest.mock as mock

    with app.app_context():
        runner = app.test_cli_runner()
        with mock.patch(
            "app.application.services.transaction_reminder_service.dispatch_due_transaction_reminders",
            side_effect=RuntimeError("DB connection lost"),
        ):
            result = runner.invoke(args=["reminders", "dispatch-due-soon"])

    assert result.exit_code == 1
    assert "ERROR" in result.output


def test_dispatch_due_soon_dry_run_does_not_send(app) -> None:
    runner = app.test_cli_runner()
    result = runner.invoke(args=["reminders", "dispatch-due-soon", "--dry-run"])

    assert result.exit_code == 0
    assert "[dry-run]" in result.output

    outbox = get_email_outbox()
    assert len(outbox) == 0


def test_dispatch_trial_ending_cli_sends_reminder(app) -> None:
    from datetime import datetime, time

    from app.models.subscription import Subscription, SubscriptionStatus

    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Trial CLI User",
            email="trial-cli@email.com",
            password="hash",
        )
        db.session.add(user)
        db.session.flush()
        db.session.add(
            Subscription(
                user_id=user.id,
                plan_code="trial",
                status=SubscriptionStatus.TRIALING,
                trial_ends_at=datetime.combine(
                    date.today() + timedelta(days=2), time(hour=12)
                ),
            )
        )
        db.session.commit()

        runner = app.test_cli_runner()
        result = runner.invoke(args=["reminders", "dispatch-trial-ending"])

        assert result.exit_code == 0
        assert "trial-ending reminders:" in result.output
        assert "sent=1" in result.output
        outbox = get_email_outbox()
        assert len(outbox) == 1
        assert outbox[0]["tag"] == "billing_trial_ending_2d"
        outbox.clear()


def test_dispatch_trial_ending_cli_dry_run_does_not_send(app) -> None:
    runner = app.test_cli_runner()
    result = runner.invoke(args=["reminders", "dispatch-trial-ending", "--dry-run"])

    assert result.exit_code == 0
    assert "[dry-run]" in result.output
    assert len(get_email_outbox()) == 0


def test_dispatch_trial_ending_cli_unexpected_error_exits_nonzero(app) -> None:
    import unittest.mock as mock

    with app.app_context():
        runner = app.test_cli_runner()
        with mock.patch(
            "app.application.services.trial_ending_reminder_service.dispatch_trial_ending_reminders",
            side_effect=RuntimeError("DB connection lost"),
        ):
            result = runner.invoke(args=["reminders", "dispatch-trial-ending"])

    assert result.exit_code == 1
    assert "ERROR" in result.output
