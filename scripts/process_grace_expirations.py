"""#1599: Process billing grace-period expirations.

Downgrade PAST_DUE subscriptions whose dunning grace window lapsed without a
successful payment retry: PAST_DUE → EXPIRED, which revokes premium entitlements
through the normal ``apply_subscription_snapshot`` machinery.

Run this on a daily cron (via ``flask billing expire-grace`` or this script).

Usage
-----
    python scripts/process_grace_expirations.py [--dry-run]

Environment
-----------
``DATABASE_URL`` must be set (or the application ``.env`` loaded). The script
bootstraps a minimal Flask application context so all ORM models are available.
``BILLING_GRACE_PERIOD_DAYS`` controls the window length (default 5) and is
applied when the grace window is *opened* (on ``payment_failed``), not here.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

    from app.models.subscription import Subscription

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
        description="Downgrade subscriptions whose dunning grace window lapsed unpaid."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print candidates without committing changes.",
    )
    return parser.parse_args()


def _notify_grace_expired(sub: Subscription) -> None:
    """Send the "downgrade por falta de pagamento" email (#1599).

    Email failures are logged and never block the downgrade batch.
    """
    from app.application.services.billing_email_service import (
        dispatch_billing_grace_expired_email,
    )
    from app.extensions.database import db
    from app.models.user import User

    user = db.session.get(User, sub.user_id)
    if user is None:
        return
    try:
        dispatch_billing_grace_expired_email(user=user, subscription=sub)
    except Exception:
        logger.exception(
            "Failed to dispatch grace-expired email for user_id=%s",
            sub.user_id,
        )


def process_grace_expirations(
    *, dry_run: bool = False, flask_app: Flask | None = None
) -> int:
    """Downgrade PAST_DUE subscriptions whose grace window lapsed unpaid.

    Args:
        dry_run: Print candidates without committing changes.
        flask_app: Optional pre-built Flask app (tests). When omitted, a
            minimal app is bootstrapped via ``create_app``.

    Returns the count of processed subscriptions.
    """
    from app import create_app
    from app.models.subscription import Subscription, SubscriptionStatus
    from app.services.billing_adapter import BillingSubscriptionSnapshot
    from app.services.subscription_service import apply_subscription_snapshot
    from app.utils.datetime_utils import utc_now_naive

    app = flask_app or create_app(enable_http_runtime=False)

    processed = 0
    with app.app_context():
        now = utc_now_naive()
        lapsed: list[Subscription] = Subscription.query.filter(
            Subscription.status == SubscriptionStatus.PAST_DUE,
            Subscription.grace_period_ends_at.isnot(None),
            Subscription.grace_period_ends_at < now,
        ).all()

        if not lapsed:
            logger.info("No lapsed grace-period subscriptions found.")
            return 0

        downgraded: list[Subscription] = []
        for sub in lapsed:
            logger.info(
                "Grace lapsed: subscription_id=%s user_id=%s grace_period_ends_at=%s",
                sub.id,
                sub.user_id,
                sub.grace_period_ends_at,
            )
            processed += 1
            if dry_run:
                continue
            expired_snapshot: BillingSubscriptionSnapshot = {
                "status": SubscriptionStatus.EXPIRED.value
            }
            apply_subscription_snapshot(sub, expired_snapshot)
            downgraded.append(sub)

        if dry_run:
            logger.info(
                "[dry-run] Would downgrade %d lapsed grace subscription(s).", processed
            )
        else:
            logger.info("Downgraded %d lapsed grace subscription(s).", processed)
            for sub in downgraded:
                _notify_grace_expired(sub)

    return processed


def main() -> None:
    args = _parse_args()
    count = process_grace_expirations(dry_run=args.dry_run)
    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}{count} subscription(s) downgraded.")


if __name__ == "__main__":
    main()
