"""Flask CLI command — trial subscription auto-expiry.

Thin wrapper around ``scripts/process_trial_expirations.py`` so the same
logic can be invoked as a Flask CLI command in Docker / ECS environments:

    flask billing expire-trials [--dry-run]

The underlying business logic lives in (and is tested via)
``scripts/process_trial_expirations.py`` and ``tests/test_billing.py``.
"""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import AppGroup

billing_cli = AppGroup("billing", help="Billing management commands.")


@billing_cli.command("expire-trials")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print which subscriptions would expire without writing to DB.",
)
def expire_trials(dry_run: bool) -> None:
    """Downgrade TRIALING subscriptions whose trial period has ended."""
    from scripts.process_trial_expirations import process_trial_expirations

    count = process_trial_expirations(dry_run=dry_run)
    if dry_run:
        click.echo(f"[dry-run] {count} subscription(s) would be downgraded.")
    else:
        click.echo(f"{count} subscription(s) downgraded.")
    if count > 0 and not dry_run:
        raise SystemExit(0)


@billing_cli.command("expire-grace")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print which subscriptions would be downgraded without writing to DB.",
)
def expire_grace(dry_run: bool) -> None:
    """Downgrade PAST_DUE subscriptions whose dunning grace window lapsed (#1599)."""
    from scripts.process_grace_expirations import process_grace_expirations

    count = process_grace_expirations(dry_run=dry_run)
    if dry_run:
        click.echo(f"[dry-run] {count} subscription(s) would be downgraded.")
    else:
        click.echo(f"{count} subscription(s) downgraded.")


def register_trial_expiry_cli(app: Flask) -> None:
    """Register the ``billing`` CLI group on *app*."""
    app.cli.add_command(billing_cli)
