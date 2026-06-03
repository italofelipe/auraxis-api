"""Tests for the 'flask recurrence reconcile' CLI command (#1422)."""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import patch

from click.testing import CliRunner


def _invoke(app, *args: str) -> object:
    from app.cli.recurrence_cli import recurrence_cli

    runner = CliRunner()
    with app.app_context():
        return runner.invoke(recurrence_cli, ["reconcile", *args])


def _create_recurring_template(app) -> uuid.UUID:
    """Persist a monthly recurring template with a future end date."""
    with app.app_context():
        from app.extensions.database import db
        from app.models.account import Account
        from app.models.transaction import (
            RecurrenceUnit,
            Transaction,
            TransactionType,
        )
        from app.models.user import User

        uid = uuid.uuid4()
        db.session.add(
            User(
                id=uid,
                name="Rec User",
                email=f"rec-{uid.hex[:8]}@test.com",
                password="x",
            )
        )
        db.session.add(Account(user_id=uid, name="Main", account_type="checking"))
        today = date.today()
        db.session.add(
            Transaction(
                user_id=uid,
                title="Financiamento carro",
                amount=1200,
                type=TransactionType.EXPENSE,
                due_date=today,
                start_date=today,
                end_date=date(today.year + 2, today.month, 1),
                is_recurring=True,
                is_installment=False,
                recurrence_interval=1,
                recurrence_unit=RecurrenceUnit.month,
            )
        )
        db.session.commit()
        return uid


class TestRecurrenceReconcileCLI:
    def test_reconcile_reports_created_count(self, app) -> None:
        with patch(
            "app.cli.recurrence_cli.RecurrenceService.generate_missing_occurrences",
            return_value=7,
        ) as mock_gen:
            result = _invoke(app)

        assert result.exit_code == 0
        assert "created=7" in result.output
        assert mock_gen.call_count == 1

    def test_reconcile_materialises_future_occurrences(self, app) -> None:
        """End-to-end: a recurring template gains future-month occurrences."""
        user_id = _create_recurring_template(app)

        result = _invoke(app)
        assert result.exit_code == 0

        with app.app_context():
            from app.models.transaction import Transaction

            rows = Transaction.query.filter_by(
                user_id=user_id, is_recurring=True, deleted=False
            ).all()
            # Template + materialised future occurrences (rolling horizon).
            assert len(rows) > 1
            months = {(r.due_date.year, r.due_date.month) for r in rows}
            today = date.today()
            next_month = (
                (today.year + 1, 1)
                if today.month == 12
                else (today.year, today.month + 1)
            )
            assert next_month in months

    def test_dry_run_counts_without_creating(self, app) -> None:
        _create_recurring_template(app)
        with patch(
            "app.cli.recurrence_cli.RecurrenceService.generate_missing_occurrences"
        ) as mock_gen:
            result = _invoke(app, "--dry-run")

        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert "1 recurring template" in result.output
        mock_gen.assert_not_called()

    def test_reconcile_exits_nonzero_on_error(self, app) -> None:
        with patch(
            "app.cli.recurrence_cli.RecurrenceService.generate_missing_occurrences",
            side_effect=RuntimeError("db down"),
        ):
            result = _invoke(app)

        assert result.exit_code == 1
        assert "ERROR" in result.output
