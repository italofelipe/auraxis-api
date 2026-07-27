from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence, cast
from uuid import UUID

from app.extensions.database import db
from app.models.alert import Alert, AlertStatus
from app.models.transaction import Transaction, TransactionStatus
from app.models.user import User
from app.services.alert_service import _is_dispatch_allowed
from app.services.email_dlq import get_email_dlq
from app.services.email_provider import (
    EmailMessage,
    EmailProviderError,
    get_default_email_provider,
)
from app.services.email_templates.base import render_due_soon_email, web_base_url
from app.services.entitlement_service import has_entitlement
from app.utils.datetime_utils import utc_now_naive

_EMAIL_REMINDERS_FEATURE = "email_reminders"

_REMINDER_WINDOWS = {
    7: "due_soon_7_days",
    1: "due_soon_1_day",
}


@dataclass(frozen=True)
class ReminderDispatchResult:
    scanned: int
    sent: int
    skipped: int
    queued: int = 0


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time())


def _end_of_day(day: date) -> datetime:
    return datetime.combine(day, datetime.max.time())


def _existing_alert_for_window(
    *,
    user_id: UUID,
    transaction_id: UUID,
    category: str,
    day: date,
) -> Alert | None:
    return cast(
        Alert | None,
        Alert.query.filter(
            Alert.user_id == user_id,
            Alert.category == category,
            Alert.entity_type == "transaction",
            Alert.entity_id == transaction_id,
            Alert.triggered_at >= _start_of_day(day),
            Alert.triggered_at <= _end_of_day(day),
        ).first(),
    )


def _serialize_amount(value: Decimal | float | int | object) -> str:
    try:
        return f"{Decimal(str(value)):.2f}"
    except Exception:
        return str(value)


def _build_subject(*, days_before_due: int, title: str, amount_str: str) -> str:
    if days_before_due == 1:
        return f"Amanhã vence: {title} (R$ {amount_str})"
    return f"Vence em {days_before_due} dias: {title} (R$ {amount_str})"


def _send_or_queue(message: EmailMessage) -> AlertStatus:
    """Send email; push to DLQ on failure. Returns the resulting alert status."""
    try:
        get_default_email_provider().send(message)
        return AlertStatus.SENT
    except EmailProviderError as exc:
        get_email_dlq().push(message, reason=str(exc))
        return AlertStatus.PENDING


def _eligible_transactions(*, target_date: date) -> Sequence[Transaction]:
    return cast(
        Sequence[Transaction],
        Transaction.query.filter(
            Transaction.deleted.is_(False),
            Transaction.due_date == target_date,
            Transaction.status.in_(
                [TransactionStatus.PENDING, TransactionStatus.POSTPONED]
            ),
        ).all(),
    )


def dispatch_due_transaction_reminders(
    *, days_before_due: int, today: date | None = None
) -> ReminderDispatchResult:
    category = _REMINDER_WINDOWS.get(days_before_due)
    if category is None:
        raise ValueError("Unsupported reminder window")

    reference_day = today or date.today()
    target_date = reference_day + timedelta(days=days_before_due)
    scanned = 0
    sent = 0
    skipped = 0
    queued = 0

    for transaction in _eligible_transactions(target_date=target_date):
        scanned += 1
        if _existing_alert_for_window(
            user_id=transaction.user_id,
            transaction_id=transaction.id,
            category=category,
            day=reference_day,
        ):
            skipped += 1
            continue
        if not _is_dispatch_allowed(transaction.user_id, category):
            skipped += 1
            continue

        if not has_entitlement(transaction.user_id, _EMAIL_REMINDERS_FEATURE):
            skipped += 1
            continue

        user = cast(User | None, db.session.get(User, transaction.user_id))
        if user is None:
            skipped += 1
            continue

        amount_str = _serialize_amount(transaction.amount)
        # #emails: deep-link the CTA straight to the expiring transaction.
        transaction_url = f"{web_base_url()}/transactions?open={transaction.id}"
        due_date_label = (
            transaction.due_date.strftime("%d/%m/%Y")
            if transaction.due_date is not None
            else ""
        )
        email_html, email_text = render_due_soon_email(
            title=transaction.title,
            amount_formatted=amount_str,
            days_before_due=days_before_due,
            due_date_label=due_date_label,
            transaction_url=transaction_url,
        )
        subject = _build_subject(
            days_before_due=days_before_due,
            title=transaction.title,
            amount_str=amount_str,
        )
        alert_status = _send_or_queue(
            EmailMessage(
                to_email=str(user.email),
                subject=subject,
                html=email_html,
                text=email_text,
                tag=category,
            )
        )
        if alert_status == AlertStatus.SENT:
            sent += 1
            sent_at = utc_now_naive()
        else:
            queued += 1
            sent_at = None

        db.session.add(
            Alert(
                user_id=transaction.user_id,
                category=category,
                status=alert_status,
                entity_type="transaction",
                entity_id=transaction.id,
                # Anchor triggered_at to reference_day so idempotency checks that
                # filter by _start_of_day(day)//_end_of_day(day) always match,
                # even when the caller passes a synthetic `today` (e.g. in tests).
                triggered_at=_start_of_day(reference_day),
                sent_at=sent_at,
            )
        )

    db.session.commit()
    return ReminderDispatchResult(
        scanned=scanned, sent=sent, skipped=skipped, queued=queued
    )
