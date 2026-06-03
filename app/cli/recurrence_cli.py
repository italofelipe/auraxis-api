"""Flask CLI command for the scheduled recurrence reconciliation job (#1422).

Command:
  flask recurrence reconcile  — materialise missing future occurrences for every
                                recurring transaction template.

This is the periodic counterpart to the inline materialisation that runs on
transaction create (``RecurrenceService.materialize_for_template``). It exists
to:
  * back-fill templates created before inline materialisation shipped (#1388),
  * extend the rolling 2-year horizon as time passes, and
  * recover occurrences whose best-effort inline materialisation failed.

Intended to run daily (see ``.github/workflows/daily-recurrence.yml``). The
underlying service is idempotent: occurrences that already exist are skipped.
"""

from __future__ import annotations

import sys
from datetime import date

import click
from flask import Flask
from flask.cli import AppGroup

from app.services.recurrence_service import RecurrenceService

recurrence_cli = AppGroup("recurrence", help="Recurring-transaction batch commands.")


@recurrence_cli.command("reconcile")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report how many recurring templates exist without creating occurrences.",
)
def reconcile(dry_run: bool) -> None:
    """Materialise missing future occurrences for all recurring templates.

    Idempotent and safe to run repeatedly. Exits non-zero only on an
    unhandled error so the scheduler can surface failures.
    """
    if dry_run:
        from app.models.transaction import Transaction

        count = Transaction.query.filter_by(is_recurring=True, deleted=False).count()
        click.echo(f"recurrence reconcile dry-run: {count} recurring template(s).")
        sys.exit(0)

    try:
        created = RecurrenceService.generate_missing_occurrences(
            reference_date=date.today()
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(f"recurrence reconcile ERROR: {exc}", err=True)
        sys.exit(1)

    click.echo(f"recurrence reconcile: created={created}")
    sys.exit(0)


def register_recurrence_commands(app: Flask) -> None:
    """Register the ``recurrence`` CLI group on *app*."""
    app.cli.add_command(recurrence_cli)


__all__ = ["recurrence_cli", "register_recurrence_commands"]
