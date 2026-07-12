"""Flask CLI commands — transaction, email-verification and trial reminders.

Dispatches email reminders:

    flask reminders dispatch-due-soon [--dry-run]
    flask reminders dispatch-email-verification [--dry-run]
    flask reminders dispatch-trial-ending [--dry-run] [--days N]

Business logic lives in
``app.application.services.transaction_reminder_service``,
``app.application.services.email_verification_reminder_service`` and
``app.application.services.trial_ending_reminder_service``.
"""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import AppGroup

reminders_cli = AppGroup("reminders", help="Reminder dispatch commands.")


@reminders_cli.command("dispatch-due-soon")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be sent without dispatching emails.",
)
@click.pass_context
def dispatch_due_soon(ctx: click.Context, dry_run: bool) -> None:
    """Send reminders for transactions due in 7 days and 1 day."""
    import sys

    if dry_run:
        click.echo("[dry-run] Would dispatch reminders for 7-day and 1-day windows.")
        return

    from app.application.services.transaction_reminder_service import (
        dispatch_due_transaction_reminders,
    )

    exit_code = 0
    for window in (7, 1):
        try:
            result = dispatch_due_transaction_reminders(days_before_due=window)
            click.echo(
                f"{window}-day reminders: "
                f"scanned={result.scanned} sent={result.sent} "
                f"skipped={result.skipped} queued={result.queued}"
            )
        except Exception as exc:  # noqa: BLE001
            click.echo(
                f"ERROR {window}-day reminders: unexpected failure — {exc}",
                err=True,
            )
            exit_code = 1

    sys.exit(exit_code)


@reminders_cli.command("dispatch-email-verification")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be sent without dispatching emails.",
)
@click.pass_context
def dispatch_email_verification(ctx: click.Context, dry_run: bool) -> None:
    """Send D-7 and D-1 reminders for the email verification grace period."""
    import sys

    if dry_run:
        click.echo(
            "[dry-run] Would dispatch verification reminders for D-7 and D-1 windows."
        )
        return

    from app.application.services.email_verification_reminder_service import (
        dispatch_email_verification_reminders,
    )

    exit_code = 0
    for window in (7, 1):
        try:
            result = dispatch_email_verification_reminders(days_until_deadline=window)
            click.echo(
                f"D-{window} verification reminders: "
                f"scanned={result.scanned} sent={result.sent} "
                f"skipped={result.skipped} queued={result.queued}"
            )
        except Exception as exc:  # noqa: BLE001
            click.echo(
                f"ERROR D-{window} verification reminders: unexpected failure — {exc}",
                err=True,
            )
            exit_code = 1

    sys.exit(exit_code)


@reminders_cli.command("dispatch-trial-ending")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would be sent without dispatching emails.",
)
@click.option(
    "--days",
    default=2,
    show_default=True,
    type=int,
    help="Countdown window in days before trial_ends_at.",
)
@click.pass_context
def dispatch_trial_ending(ctx: click.Context, dry_run: bool, days: int) -> None:
    """Send D-N reminders for TRIALING subscriptions about to end (#1555)."""
    import sys

    if dry_run:
        click.echo(
            f"[dry-run] Would dispatch trial-ending reminders for the D-{days} window."
        )
        return

    from app.application.services.trial_ending_reminder_service import (
        dispatch_trial_ending_reminders,
    )

    exit_code = 0
    try:
        result = dispatch_trial_ending_reminders(days_until_trial_end=days)
        click.echo(
            f"D-{days} trial-ending reminders: "
            f"scanned={result.scanned} sent={result.sent} "
            f"skipped={result.skipped} queued={result.queued}"
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(
            f"ERROR D-{days} trial-ending reminders: unexpected failure — {exc}",
            err=True,
        )
        exit_code = 1

    sys.exit(exit_code)


def register_reminders_commands(app: Flask) -> None:
    """Register the ``reminders`` CLI group on *app*."""
    app.cli.add_command(reminders_cli)
