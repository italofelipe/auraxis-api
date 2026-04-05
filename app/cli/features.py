"""
app/cli/features.py — Flask CLI commands for feature flag management.

Usage examples
--------------
    flask features set tools.fgts_simulator --enabled --canary 10
    flask features set tools.fgts_simulator --disabled
    flask features get tools.fgts_simulator
    flask features list
    flask features delete tools.fgts_simulator
"""

from __future__ import annotations

import json

import click

from app.services.feature_flag_service import get_feature_flag_service


@click.group()
def features() -> None:
    """Feature flag management."""


@features.command("set")
@click.argument("name")
@click.option("--enabled/--disabled", default=True, help="Enable or disable the flag.")
@click.option(
    "--canary",
    default=0,
    type=click.IntRange(0, 100),
    help="Canary rollout percentage (0 = all users, 1-99 = subset, 100 = all users).",
)
@click.option(
    "--description", default="", help="Human-readable description of the flag."
)
def set_flag(name: str, enabled: bool, canary: int, description: str) -> None:
    """Create or update feature flag NAME."""
    svc = get_feature_flag_service()
    svc.set_flag(
        name, enabled=enabled, canary_percentage=canary, description=description
    )
    state = "enabled" if enabled else "disabled"
    click.echo(f"flag={name} {state} canary={canary}%")


@features.command("get")
@click.argument("name")
def get_flag(name: str) -> None:
    """Show the current configuration of feature flag NAME."""
    svc = get_feature_flag_service()
    config = svc.get_flag(name)
    if config is None:
        click.echo(f"flag={name} not found")
        return
    click.echo(json.dumps({name: config.to_dict()}, indent=2))


@features.command("list")
def list_flags() -> None:
    """List all feature flags stored in Redis."""
    svc = get_feature_flag_service()
    flags = svc.list_flags()
    if not flags:
        click.echo("No feature flags found.")
        return
    output = {flag_name: cfg.to_dict() for flag_name, cfg in flags.items()}
    click.echo(json.dumps(output, indent=2))


@features.command("delete")
@click.argument("name")
def delete_flag(name: str) -> None:
    """Remove feature flag NAME from Redis (kill switch / cleanup)."""
    svc = get_feature_flag_service()
    svc.delete_flag(name)
    click.echo(f"flag={name} deleted")


__all__ = ["features"]
