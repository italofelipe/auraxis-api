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


@billing_cli.command("checkout-funnel")
@click.option(
    "--days",
    type=int,
    default=7,
    help="Window in days to report (0 = since the beginning).",
)
@click.option(
    "--abandon-after",
    type=int,
    default=45,
    help="Minutes a started checkout waits before counting as abandoned.",
)
@click.option(
    "--surface",
    type=str,
    default=None,
    help="Restrict to one origin surface (landing, app).",
)
def checkout_funnel(days: int, abandon_after: int, surface: str | None) -> None:
    """Report started / completed / abandoned checkouts for a window."""
    from datetime import timedelta

    from app.application.services.checkout_funnel_service import summarize_funnel
    from app.utils.datetime_utils import utc_now_naive

    since = None if days <= 0 else utc_now_naive() - timedelta(days=days)
    funnel = summarize_funnel(
        since=since,
        abandon_after=timedelta(minutes=abandon_after),
        return_surface=surface,
    )

    window = "desde o início" if since is None else f"últimos {days} dia(s)"
    scope = f" · superfície {surface}" if surface else ""
    click.echo(f"Funil de checkout — {window}{scope}")
    click.echo(f"  iniciados   {funnel.started}")
    click.echo(f"  concluídos  {funnel.completed}")
    click.echo(f"  abandonados {funnel.abandoned}  (sem pagar após {abandon_after}min)")
    click.echo(f"  falharam    {funnel.failed}  (gateway recusou criar o checkout)")
    click.echo(f"  em aberto   {funnel.pending}  (ainda dentro da janela)")
    click.echo(f"  conversão   {funnel.conversion_rate}%  (dos resolvidos)")


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


@billing_cli.command("reconcile-subscriptions")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report drift without writing changes.",
)
def reconcile_subscriptions_command(dry_run: bool) -> None:
    """Realign subscriptions that drifted from the gateway (lost webhook) (#1600)."""
    from scripts.reconcile_subscriptions import reconcile_subscriptions

    summary = reconcile_subscriptions(dry_run=dry_run)
    prefix = "[dry-run] " if dry_run else ""
    click.echo(
        f"{prefix}checked={summary['checked']} "
        f"reconciled={summary['reconciled']} errors={summary['errors']}"
    )


def register_trial_expiry_cli(app: Flask) -> None:
    """Register the ``billing`` CLI group on *app*."""
    app.cli.add_command(billing_cli)
