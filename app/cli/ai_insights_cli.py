"""Flask CLI commands for scheduled AI insights batch jobs (#1215, #1216).

Commands:
  flask ai weekly-insights   — Premium users, runs every Saturday 03:00 UTC
  flask ai monthly-insights  — All users, runs on the 1st of each month 03:00 UTC

Both commands follow the same pattern:
  1. Query eligible users
  2. Check idempotency (skip if already generated today)
  3. Call AIAdvisoryService
  4. Log per-user result; continue on individual failures
  5. Exit non-zero if ALL users failed (total failure)
"""

from __future__ import annotations

import html as html_lib
import json
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click
from flask import Flask
from flask.cli import AppGroup

from app.extensions.database import db
from app.models.ai_insight import AIInsight, InsightType
from app.models.entitlement import Entitlement
from app.models.user import User
from app.services.ai_advisory_service import AIAdvisoryService
from app.services.ai_insight_audit import get_ai_insight_run_dossier
from app.services.analysis_ready_notification_service import (
    dispatch_analysis_ready_notification,
)

ai_insights_cli = AppGroup("ai", help="Scheduled AI insights batch commands.")

_BRT = timezone(timedelta(hours=-3))


def _brt_today() -> date:
    return datetime.now(_BRT).date()


def _premium_user_ids() -> list[uuid.UUID]:
    """Return UUIDs of all non-deleted users with advanced_simulations entitlement."""
    rows = (
        db.session.query(Entitlement.user_id)
        .join(User, User.id == Entitlement.user_id)
        .filter(
            Entitlement.feature_key == "advanced_simulations",
            User.deleted_at.is_(None),
        )
        .distinct()
        .all()
    )
    return [r.user_id for r in rows]


def _all_active_user_ids() -> list[uuid.UUID]:
    """Return UUIDs of all non-deleted users (Free + Premium)."""
    rows = db.session.query(User.id).filter(User.deleted_at.is_(None)).all()
    return [r.id for r in rows]


def _monthly_anchor(month: str | None) -> date:
    if month is not None:
        year, mon = int(month[:4]), int(month[5:7])
        return date(year, mon, 1)

    today = _brt_today()
    first_of_month = today.replace(day=1)
    prev_month_last = first_of_month - timedelta(days=1)
    return prev_month_last.replace(day=1)


def _period_label(*, insight_type: InsightType, anchor_date: date) -> str:
    if insight_type == InsightType.weekly:
        iso = anchor_date.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if insight_type == InsightType.monthly:
        return anchor_date.strftime("%Y-%m")
    return anchor_date.isoformat()


def _already_has_insight(
    *,
    user_id: uuid.UUID,
    insight_type: InsightType,
    period_label: str,
) -> bool:
    exists = (
        db.session.query(AIInsight.id)
        .filter_by(
            user_id=user_id,
            insight_type=insight_type,
            period_label=period_label,
        )
        .first()
    )
    return exists is not None


def _parse_uuid_option(value: str | None, *, option_name: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise click.ClickException(f"{option_name} deve ser UUID válido") from exc


def _render_dossier_html(payload: dict[str, Any]) -> str:
    title = f"AI Insight Dossier {payload['run']['id']}"
    pretty = html_lib.escape(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return (
        "<!doctype html>\n"
        '<html lang="pt-BR">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f"  <title>{html_lib.escape(title)}</title>\n"
        "  <style>"
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "margin:32px;color:#111827;background:#f9fafb;}"
        "main{max-width:1100px;margin:0 auto;}"
        "pre{white-space:pre-wrap;background:#fff;border:1px solid #d1d5db;"
        "border-radius:8px;padding:16px;overflow:auto;}"
        "h1{font-size:22px;margin:0 0 16px;}"
        "</style>\n"
        "</head>\n"
        "<body><main>\n"
        f"<h1>{html_lib.escape(title)}</h1>\n"
        f"<pre>{pretty}</pre>\n"
        "</main></body>\n"
        "</html>\n"
    )


def _write_dossier_files(
    *,
    payload: dict[str, Any],
    output_dir: Path,
    output_format: str,
) -> list[Path]:
    run_id = str(payload["run"]["id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if output_format in {"json", "both"}:
        json_path = output_dir / f"ai-insight-dossier-{run_id}.json"
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        written.append(json_path)

    if output_format in {"html", "both"}:
        html_path = output_dir / f"ai-insight-dossier-{run_id}.html"
        html_path.write_text(_render_dossier_html(payload), encoding="utf-8")
        written.append(html_path)

    return written


def _notification_preview(result: dict[str, Any]) -> str:
    """Build a short email preview from a generated insight result.

    Uses the insight summary truncated to ~280 chars on a word boundary; falls
    back to the service default when no summary is present.
    """
    summary = str(result.get("summary") or "").strip()
    if not summary:
        return "Sua análise financeira está disponível."
    if len(summary) <= 280:
        return summary
    return summary[:280].rsplit(" ", 1)[0]


def _run_batch(
    *,
    user_ids: list[uuid.UUID],
    insight_type: InsightType,
    anchor_date: date,
    label: str,
    dry_run: bool,
    dry_run_subject: str,
) -> int:
    """Run a batch insight generation job.

    Returns:
        Exit code: 0 if at least one user succeeded (or no users); 1 if all failed.
    """
    if not user_ids:
        click.echo(f"{label}: processed=0 failures=0 skipped=0 cost_usd=0.000000")
        return 0

    if dry_run:
        click.echo(
            f"{label} dry-run: {len(user_ids)} {dry_run_subject} — no calls made."
        )
        return 0

    period_label = _period_label(insight_type=insight_type, anchor_date=anchor_date)
    processed = 0
    failures = 0
    skipped = 0
    total_cost = 0.0

    for user_id in user_ids:
        if _already_has_insight(
            user_id=user_id,
            insight_type=insight_type,
            period_label=period_label,
        ):
            skipped += 1
            continue

        service = AIAdvisoryService(user_id=user_id)
        try:
            result = service.generate_financial_insights(
                period_type=insight_type.value,
                anchor_date=anchor_date,
            )
            if result.get("cached") is True:
                skipped += 1
            else:
                total_cost += float(result.get("cost_usd", 0))
                processed += 1
                # Notify the user that a fresh analysis is ready. This is the
                # ONLY place the "analysis ready" email is sent — reads of
                # /ai/insights/weekly-summary are side-effect free. Best-effort:
                # a notification failure must not abort the batch.
                try:
                    dispatch_analysis_ready_notification(
                        user_id=user_id,
                        summary_preview=_notification_preview(result),
                    )
                except Exception as exc:  # noqa: BLE001
                    click.echo(
                        f"{label} NOTIFY-WARN user={user_id} error={exc}",
                        err=True,
                    )
        except Exception as exc:  # noqa: BLE001
            click.echo(
                f"{label} ERROR user={user_id} error={exc}",
                err=True,
            )
            failures += 1

    click.echo(
        f"{label}: processed={processed} failures={failures} "
        f"skipped={skipped} cost_usd={total_cost:.6f} period={period_label}"
    )

    if failures > 0 and processed == 0 and skipped == 0:
        return 1
    return 0


# ---------------------------------------------------------------------------
# weekly-insights command
# ---------------------------------------------------------------------------


@ai_insights_cli.command("weekly-insights")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print eligible user count without making LLM calls.",
)
def weekly_insights(dry_run: bool) -> None:
    """Generate weekly financial briefing for all Premium users.

    Intended to run every Saturday at 03:00 UTC (00:00 BRT).
    Idempotent: skips users who already have a weekly summary today.
    """
    user_ids = _premium_user_ids()
    exit_code = _run_batch(
        user_ids=user_ids,
        insight_type=InsightType.weekly,
        anchor_date=_brt_today(),
        label="weekly_insights",
        dry_run=dry_run,
        dry_run_subject="eligible Premium users",
    )
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# monthly-insights command
# ---------------------------------------------------------------------------


@ai_insights_cli.command("monthly-insights")
@click.option(
    "--month",
    default=None,
    metavar="YYYY-MM",
    help="Month to generate insights for. Defaults to the previous calendar month.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print eligible user count without making LLM calls.",
)
def monthly_insights(month: str | None, dry_run: bool) -> None:
    """Generate monthly spending recap for ALL active users (Free + Premium).

    Intended to run on the 1st of each month at 03:00 UTC (00:00 BRT).
    Idempotent: skips users who already have a monthly summary today.
    """
    anchor_date = _monthly_anchor(month)
    month_label = anchor_date.strftime("%Y-%m")
    user_ids = _all_active_user_ids()
    exit_code = _run_batch(
        user_ids=user_ids,
        insight_type=InsightType.monthly,
        anchor_date=anchor_date,
        label="monthly_insights",
        dry_run=dry_run,
        dry_run_subject=f"eligible users (Free + Premium) for month={month_label}",
    )
    if not dry_run:
        click.echo(f"monthly_insights month={month_label}")
    sys.exit(exit_code)


@ai_insights_cli.command("export-dossier")
@click.option("--run-id", default=None, help="AIInsightRun UUID to export.")
@click.option("--user-id", default=None, help="Filter by user UUID.")
@click.option(
    "--period-type",
    default=None,
    type=click.Choice(["daily", "weekly", "monthly"]),
    help="Filter by insight period type.",
)
@click.option("--period-label", default=None, help="Filter by period label.")
@click.option("--insight-id", default=None, help="Filter by AIInsight UUID.")
@click.option(
    "--output-dir",
    default=".",
    type=click.Path(file_okay=False, path_type=Path),
    help="Local directory where dossier files will be written.",
)
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "html", "both"]),
    show_default=True,
    help="Dossier output format.",
)
def export_dossier(
    run_id: str | None,
    user_id: str | None,
    period_type: str | None,
    period_label: str | None,
    insight_id: str | None,
    output_dir: Path,
    output_format: str,
) -> None:
    """Export an auditable AI Insight dossier without calling an LLM."""

    if not any((run_id, user_id, period_type, period_label, insight_id)):
        raise click.ClickException(
            "Informe ao menos um filtro: --run-id, --user-id, --period-type, "
            "--period-label ou --insight-id."
        )

    payload = get_ai_insight_run_dossier(
        run_id=_parse_uuid_option(run_id, option_name="--run-id"),
        user_id=_parse_uuid_option(user_id, option_name="--user-id"),
        period_type=period_type,
        period_label=period_label,
        insight_id=_parse_uuid_option(insight_id, option_name="--insight-id"),
    )
    paths = _write_dossier_files(
        payload=payload,
        output_dir=output_dir,
        output_format=output_format,
    )
    click.echo(
        "export_dossier: "
        + " ".join(f"path={path}" for path in paths)
        + f" run_id={payload['run']['id']}"
    )


def register_ai_insights_commands(app: Flask) -> None:
    """Register the ``ai`` CLI group on *app*."""
    app.cli.add_command(ai_insights_cli)


__all__ = [
    "ai_insights_cli",
    "register_ai_insights_commands",
]
