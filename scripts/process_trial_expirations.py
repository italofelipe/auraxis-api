"""H-PROD-01: Process trial expirations — downgrade expired trial subscriptions.

Run this script on a cron schedule (e.g. daily) to detect users whose 14-day
trial period has ended and downgrade them from TRIALING → FREE.

Usage
-----
    python scripts/process_trial_expirations.py [--dry-run]

Options
-------
--dry-run   Print which subscriptions would be downgraded without committing.

Environment
-----------
DATABASE_URL must be set (or the application .env must be loaded).  The script
bootstraps a minimal Flask application context so all ORM models are available.
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

# ---------------------------------------------------------------------------
# Bootstrap: ensure the project root is on sys.path
# ---------------------------------------------------------------------------

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
        description="Downgrade subscriptions whose trial period has expired."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print candidates without committing changes.",
    )
    return parser.parse_args()


def _notify_trial_expired(sub: Subscription) -> None:
    """Send the "downgrade efetivado" email for an expired trial (#1555).

    Email failures are logged and never block the downgrade batch.
    """
    from app.application.services.billing_email_service import (
        dispatch_trial_expired_email,
    )
    from app.extensions.database import db
    from app.models.user import User

    user = db.session.get(User, sub.user_id)
    if user is None:
        return
    try:
        dispatch_trial_expired_email(user=user, subscription=sub)
    except Exception:
        logger.exception(
            "Failed to dispatch trial-expired email for user_id=%s",
            sub.user_id,
        )


def process_trial_expirations(
    *, dry_run: bool = False, flask_app: Flask | None = None
) -> int:
    """Downgrade all expired TRIALING subscriptions to FREE.

    Args:
        dry_run: Print candidates without committing changes.
        flask_app: Optional pre-built Flask app (tests). When omitted, a
            minimal app is bootstrapped via ``create_app``.

    Returns the count of processed subscriptions.
    """
    from app import create_app
    from app.extensions.database import db
    from app.models.subscription import Subscription, SubscriptionStatus
    from app.services.entitlement_service import deactivate_premium
    from app.utils.datetime_utils import utc_now_naive

    app = flask_app or create_app(enable_http_runtime=False)

    processed = 0
    with app.app_context():
        now = utc_now_naive()
        expired_subs: list[Subscription] = Subscription.query.filter(
            Subscription.status == SubscriptionStatus.TRIALING,
            Subscription.trial_ends_at.isnot(None),
            Subscription.trial_ends_at <= now,
        ).all()

        if not expired_subs:
            logger.info("No expired trial subscriptions found.")
            return 0

        for sub in expired_subs:
            logger.info(
                "Expiring trial: subscription_id=%s user_id=%s trial_ends_at=%s",
                sub.id,
                sub.user_id,
                sub.trial_ends_at,
            )
            if not dry_run:
                sub.status = SubscriptionStatus.FREE
                sub.plan_code = "free"
                db.session.add(sub)
                try:
                    deactivate_premium(sub.user_id)
                except Exception:
                    logger.exception(
                        "Failed to revoke premium entitlements for user_id=%s",
                        sub.user_id,
                    )
            processed += 1

        if not dry_run:
            db.session.commit()
            logger.info("Downgraded %d expired trial subscription(s).", processed)
            for sub in expired_subs:
                _notify_trial_expired(sub)
        else:
            logger.info(
                "[dry-run] Would downgrade %d expired trial subscription(s).", processed
            )

    return processed


def main() -> None:
    args = _parse_args()
    count = process_trial_expirations(dry_run=args.dry_run)
    if args.dry_run:
        print(f"[dry-run] {count} subscription(s) would be downgraded.")
    else:
        print(f"{count} subscription(s) downgraded.")


if __name__ == "__main__":
    main()
