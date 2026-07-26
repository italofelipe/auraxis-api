"""#1600: Reconcile local subscriptions against the payment gateway.

The subscription sync is lazy (``GET /subscriptions/me``) plus webhooks. A
webhook that is lost and never redelivered — for a user who does not open the
app — leaves a **permanent drift**: paid without premium, or canceled while still
premium. The webhook-retry job only reprocesses events we *received*; it cannot
cover ones never delivered.

This job polls the gateway for every active/trialing/past_due subscription with a
real provider id and applies the authoritative snapshot when it diverges from the
local state. A recurring drift count is a signal the webhook path is broken, so it
raises a Sentry alert.

Usage
-----
    python scripts/reconcile_subscriptions.py [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask

    from app.models.subscription import Subscription
    from app.services.billing_adapter import BillingSubscriptionSnapshot

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile local subscriptions against the payment gateway."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Report drift without writing changes.",
    )
    return parser.parse_args()


def _snapshot_diverges(
    sub: Subscription, snapshot: BillingSubscriptionSnapshot
) -> bool:
    """Whether the gateway snapshot disagrees with the local subscription.

    Only fields the snapshot actually carries are compared — ``get_subscription``
    may omit the plan, and a missing field must never be read as "downgrade".
    """
    snap_status = str(snapshot.get("status") or "").strip()
    if snap_status and snap_status != sub.status.value:
        return True
    snap_plan = snapshot.get("plan_code")
    if snap_plan and str(snap_plan) != sub.plan_code:
        return True
    return False


def _alert_drift(reconciled: int, drifted_ids: list[str]) -> None:
    """Log + Sentry alert when the gateway corrected local state (#1600).

    Drift means a webhook was lost: loud enough to investigate the webhook path.
    """
    logger.error(
        "reconcile-subscriptions: corrected %d drifted subscription(s) — a lost "
        "webhook is likely; investigate delivery. ids=%s",
        reconciled,
        ",".join(drifted_ids[:50]),
    )
    try:
        import sentry_sdk

        sentry_sdk.capture_message(
            f"reconcile-subscriptions corrected {reconciled} drifted subscription(s)",
            level="warning",
        )
    except Exception:  # noqa: BLE001 — Sentry is best-effort, never block the job
        logger.debug("Sentry capture skipped (SDK unavailable).")


def reconcile_subscriptions(
    *, dry_run: bool = False, flask_app: Flask | None = None
) -> dict[str, Any]:
    """Poll the gateway and realign every drifted subscription.

    Returns a summary dict: ``{"checked", "reconciled", "errors"}``.
    """
    from app import create_app
    from app.models.subscription import Subscription, SubscriptionStatus
    from app.services.billing_adapter import get_default_billing_provider
    from app.services.subscription_service import apply_subscription_snapshot

    app = flask_app or create_app(enable_http_runtime=False)

    checked = 0
    reconciled = 0
    errors = 0
    drifted_ids: list[str] = []

    with app.app_context():
        provider = get_default_billing_provider()
        candidates: list[Subscription] = Subscription.query.filter(
            Subscription.status.in_(
                [
                    SubscriptionStatus.ACTIVE,
                    SubscriptionStatus.TRIALING,
                    SubscriptionStatus.PAST_DUE,
                ]
            ),
            Subscription.provider_subscription_id.isnot(None),
        ).all()

        for sub in candidates:
            provider_id = sub.provider_subscription_id
            # A ``bill_`` placeholder means the completed webhook never arrived —
            # there is no real subscription to poll yet, so skip it.
            if not provider_id or provider_id.startswith("bill_"):
                continue
            checked += 1
            try:
                snapshot = provider.get_subscription(provider_id)
            except Exception:  # noqa: BLE001 — one bad poll must not kill the batch
                errors += 1
                logger.warning(
                    "reconcile-subscriptions: get_subscription failed for "
                    "subscription_id=%s provider_id=%s — skipping",
                    sub.id,
                    provider_id,
                )
                continue

            if not _snapshot_diverges(sub, snapshot):
                continue

            reconciled += 1
            drifted_ids.append(str(sub.id))
            logger.info(
                "reconcile-subscriptions: drift on subscription_id=%s user_id=%s "
                "local_status=%s gateway_status=%s%s",
                sub.id,
                sub.user_id,
                sub.status.value,
                snapshot.get("status"),
                " (dry-run)" if dry_run else "",
            )
            if not dry_run:
                apply_subscription_snapshot(sub, snapshot)

        if reconciled and not dry_run:
            _alert_drift(reconciled, drifted_ids)

    logger.info(
        "reconcile-subscriptions: checked=%d reconciled=%d errors=%d%s",
        checked,
        reconciled,
        errors,
        " (dry-run)" if dry_run else "",
    )
    return {"checked": checked, "reconciled": reconciled, "errors": errors}


def main() -> None:
    args = _parse_args()
    summary = reconcile_subscriptions(dry_run=args.dry_run)
    prefix = "[dry-run] " if args.dry_run else ""
    print(
        f"{prefix}checked={summary['checked']} "
        f"reconciled={summary['reconciled']} errors={summary['errors']}"
    )


if __name__ == "__main__":
    main()
