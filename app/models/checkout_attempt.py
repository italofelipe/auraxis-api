# mypy: disable-error-code="name-defined"
"""CheckoutAttempt — one row per attempt to start a paid subscription.

``Subscription`` holds a single row per user carrying the *current* state, so a
checkout that never becomes a payment leaves no trace at all.  Without a record
of the attempt there is no denominator: "how many people tried to subscribe and
did not finish" is unanswerable, and a broken payment path can stay broken
without emitting a single signal.

The gateway does not help here either — it emits ``subscription.*``
events for trial, completion, cancellation, past due and refunds, but **nothing
for an abandoned checkout**.  Abandonment only exists if we record the attempt.

Abandonment is deliberately **not** a stored status.  It is the absence of a
completion after some time, and storing it would need a sweep job that can lag,
run twice, or disagree with the timestamps it is derived from — a second source
of truth for something the timestamps already say.  Queries apply an explicit
cutoff instead; see ``checkout_funnel_service``.

Statuses
--------
started   — checkout created at the provider; the buyer holds a payment URL.
completed — a webhook promoted this attempt into an active/trialing subscription.
failed    — the provider refused to create the checkout; no URL ever existed.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive


class CheckoutAttemptStatus(str, enum.Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class CheckoutAttempt(db.Model):
    """Audit row for every attempt to open a paid checkout."""

    __tablename__ = "checkout_attempts"

    id = db.Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    # What was being sold
    plan_slug = db.Column(db.String(60), nullable=False)
    plan_code = db.Column(db.String(40), nullable=True)
    billing_cycle = db.Column(db.String(20), nullable=True)

    # Where the buyer came from — landing and in-app checkouts convert very
    # differently, and telling them apart is the point of tracking the funnel.
    return_surface = db.Column(db.String(40), nullable=True)

    # Provider correlation.  ``provider_checkout_id`` is the ``bill_…`` handed to
    # the buyer; the subscription id only exists once payment happens, so the
    # customer id is what links an inbound webhook back to this attempt.
    provider = db.Column(db.String(40), nullable=False)
    provider_checkout_id = db.Column(db.String(120), nullable=True, index=True)
    provider_customer_id = db.Column(db.String(120), nullable=True, index=True)
    provider_subscription_id = db.Column(db.String(120), nullable=True, index=True)

    status = db.Column(
        # native_enum=False per the repo migration convention: a native PG type
        # makes Alembic emit CREATE TYPE before the migration runs.
        db.Enum(
            *[member.value for member in CheckoutAttemptStatus],
            name="checkout_attempt_status",
            native_enum=False,
        ),
        nullable=False,
        default=CheckoutAttemptStatus.STARTED.value,
        index=True,
    )
    failure_reason = db.Column(db.String(200), nullable=True)

    started_at = db.Column(
        db.DateTime, nullable=False, default=utc_now_naive, index=True
    )
    completed_at = db.Column(db.DateTime, nullable=True)

    def mark_completed(
        self,
        *,
        provider_subscription_id: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Record that this attempt turned into a paid subscription."""
        self.status = CheckoutAttemptStatus.COMPLETED.value
        self.completed_at = now or utc_now_naive()
        if provider_subscription_id:
            self.provider_subscription_id = provider_subscription_id

    def mark_failed(self, *, reason: str, now: datetime | None = None) -> None:
        """Record that the provider never produced a payment URL."""
        self.status = CheckoutAttemptStatus.FAILED.value
        self.failure_reason = reason[:200]
        self.completed_at = now or utc_now_naive()

    def __repr__(self) -> str:
        return (
            f"<CheckoutAttempt user={self.user_id} plan={self.plan_slug}"
            f" status={self.status}>"
        )
