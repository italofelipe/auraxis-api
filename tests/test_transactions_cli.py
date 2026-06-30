"""Tests for the 'flask transactions auto-settle' CLI command (#1516)."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner


def _invoke(app, *args: str) -> object:
    from app.cli.transactions_cli import transactions_cli

    runner = CliRunner()
    with app.app_context():
        return runner.invoke(transactions_cli, ["auto-settle", *args])


class TestAutoSettleCLI:
    def test_reports_settled_count(self, app) -> None:
        with patch(
            "app.cli.transactions_cli.TransactionAutoSettleService.settle_due",
            return_value=5,
        ) as mock_settle:
            result = _invoke(app)

        assert result.exit_code == 0
        assert "settled=5" in result.output
        assert mock_settle.call_count == 1

    def test_dry_run_counts_without_settling(self, app) -> None:
        with (
            patch(
                "app.cli.transactions_cli.TransactionAutoSettleService.count_due",
                return_value=3,
            ),
            patch(
                "app.cli.transactions_cli.TransactionAutoSettleService.settle_due"
            ) as mock_settle,
        ):
            result = _invoke(app, "--dry-run")

        assert result.exit_code == 0
        assert "dry-run" in result.output
        assert "3 due transaction" in result.output
        mock_settle.assert_not_called()

    def test_exits_nonzero_on_error(self, app) -> None:
        with patch(
            "app.cli.transactions_cli.TransactionAutoSettleService.settle_due",
            side_effect=RuntimeError("db down"),
        ):
            result = _invoke(app)

        assert result.exit_code == 1
        assert "ERROR" in result.output
