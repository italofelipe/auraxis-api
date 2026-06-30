"""Flask CLI commands for transaction batch jobs (F4, #1516).

Command:
  flask transactions auto-settle  — mark opted-in transactions (``auto_settle``)
                                     as paid once they come due.

Intended to run daily (see ``.github/workflows/auto-settle.yml``). The underlying
service is idempotent: already-paid rows are skipped, and future occurrences are
never touched.
"""

from __future__ import annotations

import sys
from datetime import date

import click
from flask import Flask
from flask.cli import AppGroup

from app.services.transaction_auto_settle_service import TransactionAutoSettleService

transactions_cli = AppGroup("transactions", help="Transaction batch commands.")


@transactions_cli.command("auto-settle")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report how many due opted-in transactions exist without settling them.",
)
def auto_settle(dry_run: bool) -> None:
    """Mark due, opted-in transactions as paid.

    Idempotent and safe to run repeatedly. Exits non-zero only on an unhandled
    error so the scheduler can surface failures.
    """
    if dry_run:
        count = TransactionAutoSettleService.count_due(reference_date=date.today())
        click.echo(f"transactions auto-settle dry-run: {count} due transaction(s).")
        sys.exit(0)

    try:
        settled = TransactionAutoSettleService.settle_due(reference_date=date.today())
    except Exception as exc:  # noqa: BLE001
        click.echo(f"transactions auto-settle ERROR: {exc}", err=True)
        sys.exit(1)

    click.echo(f"transactions auto-settle: settled={settled}")
    sys.exit(0)


def register_transactions_commands(app: Flask) -> None:
    """Register the ``transactions`` CLI group on *app*."""
    app.cli.add_command(transactions_cli)


__all__ = ["transactions_cli", "register_transactions_commands"]
