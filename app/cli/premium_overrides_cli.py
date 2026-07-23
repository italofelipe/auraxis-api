"""Operational commands for migrating legacy premium override configuration."""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import AppGroup

from app.extensions.database import db
from app.models.user import User
from app.services.premium_override_service import (
    get_active_premium_override,
    grant_premium_override,
)
from app.services.subscription_service import configured_premium_override_user_ids

premium_overrides_cli = AppGroup(
    "premium-overrides", help="Manage auditable premium access overrides."
)


@premium_overrides_cli.command("migrate-env")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Report the migration without writing premium_overrides rows.",
)
def migrate_env(dry_run: bool) -> None:
    """Convert legacy environment user IDs to auditable override rows."""
    configured = configured_premium_override_user_ids()
    migrated = 0
    existing = 0
    missing = 0

    for user_id in sorted(configured, key=str):
        if db.session.get(User, user_id) is None:
            missing += 1
            click.echo(f"missing user: {user_id}", err=True)
            continue
        if get_active_premium_override(user_id) is not None:
            existing += 1
            continue
        migrated += 1
        if not dry_run:
            grant_premium_override(
                user_id=user_id,
                reason="Migrated from AURAXIS_PREMIUM_OVERRIDE_USER_IDS",
                granted_by="system:legacy-premium-override-env",
            )

    if not dry_run:
        db.session.commit()
    click.echo(
        f"premium override migration: configured={len(configured)} "
        f"migrated={migrated} existing={existing} missing={missing} "
        f"dry_run={str(dry_run).lower()}"
    )
    if missing:
        raise click.ClickException("one or more configured users do not exist")


def register_premium_override_commands(app: Flask) -> None:
    app.cli.add_command(premium_overrides_cli)


__all__ = ["premium_overrides_cli", "register_premium_override_commands"]
