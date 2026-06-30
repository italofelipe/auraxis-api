from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from app.extensions.database import db
from app.models.transaction import RecurrenceUnit, Transaction

logger = logging.getLogger(__name__)

# Safety bound: when a recurring transaction has no usable end_date, materialise
# at most this far ahead so a runaway cadence cannot flood the table.
_MAX_HORIZON_DAYS = 366 * 2


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _advance(value: date, unit: RecurrenceUnit, interval: int) -> date:
    """Advance ``value`` by one cadence step (``interval`` × ``unit``)."""
    step = max(int(interval or 1), 1)
    if unit == RecurrenceUnit.day:
        return value + timedelta(days=step)
    if unit == RecurrenceUnit.week:
        return value + timedelta(weeks=step)
    if unit == RecurrenceUnit.year:
        return _add_months(value, 12 * step)
    return _add_months(value, step)


@dataclass(frozen=True)
class RecurrenceWindow:
    start: date
    end: date


class RecurrenceService:
    @staticmethod
    def _build_window(
        transaction: Transaction, reference_date: date
    ) -> RecurrenceWindow | None:
        if (
            not transaction.is_recurring
            or transaction.deleted
            or transaction.is_installment
            or transaction.start_date is None
            or transaction.end_date is None
        ):
            return None

        if transaction.start_date > transaction.end_date:
            return None

        # Materialise up to end_date — not capped at the reference date — so
        # future months are populated. A rolling horizon bounds runaway windows
        # (e.g. a daily cadence with an end_date years away); the cron extends
        # the window on each run.
        horizon = reference_date + timedelta(days=_MAX_HORIZON_DAYS)
        window_end = min(transaction.end_date, horizon)
        if window_end < transaction.start_date:
            return None

        return RecurrenceWindow(start=transaction.start_date, end=window_end)

    @staticmethod
    def _iter_expected_due_dates(
        *,
        window: RecurrenceWindow,
        base_due_date: date,
        unit: RecurrenceUnit,
        interval: int,
    ) -> Iterable[date]:
        due_date = base_due_date
        while due_date < window.start:
            due_date = _advance(due_date, unit, interval)

        while due_date <= window.end:
            yield due_date
            due_date = _advance(due_date, unit, interval)

    @staticmethod
    def generate_missing_occurrences(reference_date: date | None = None) -> int:
        reference = reference_date or date.today()
        templates = Transaction.query.filter_by(
            is_recurring=True,
            deleted=False,
        ).all()

        logger.info(
            "recurrence: found %d recurring template(s) for reference_date=%s",
            len(templates),
            reference,
        )

        created: list[Transaction] = []
        for template in templates:
            window = RecurrenceService._build_window(template, reference)
            if window is None:
                continue
            created.extend(
                RecurrenceService._build_occurrences(template=template, window=window)
            )

        return RecurrenceService._persist(created)

    @staticmethod
    def materialize_for_template(
        template: Transaction, reference_date: date | None = None
    ) -> int:
        """Materialise future occurrences for a single recurring template.

        Called right after a recurring transaction is created so its future
        months are populated immediately, without waiting for the daily cron.
        Idempotent: skips occurrences that already exist.
        """
        reference = reference_date or date.today()
        window = RecurrenceService._build_window(template, reference)
        if window is None:
            return 0
        return RecurrenceService._persist(
            RecurrenceService._build_occurrences(template=template, window=window)
        )

    @staticmethod
    def _build_occurrences(
        *, template: Transaction, window: RecurrenceWindow
    ) -> list[Transaction]:
        occurrences: list[Transaction] = []
        expected_dates = RecurrenceService._iter_expected_due_dates(
            window=window,
            base_due_date=template.due_date,
            unit=template.recurrence_unit or RecurrenceUnit.month,
            interval=template.recurrence_interval or 1,
        )
        for due in expected_dates:
            if due == template.due_date:
                continue

            exists = Transaction.query.filter_by(
                user_id=template.user_id,
                title=template.title,
                amount=template.amount,
                type=template.type,
                due_date=due,
                is_recurring=True,
                start_date=template.start_date,
                end_date=template.end_date,
                deleted=False,
            ).first()
            if exists:
                continue

            occurrences.append(
                Transaction(
                    user_id=template.user_id,
                    title=template.title,
                    description=template.description,
                    observation=template.observation,
                    is_recurring=True,
                    is_installment=False,
                    installment_count=None,
                    recurrence_interval=template.recurrence_interval or 1,
                    recurrence_unit=template.recurrence_unit or RecurrenceUnit.month,
                    amount=template.amount,
                    currency=template.currency,
                    status=template.status,
                    type=template.type,
                    due_date=due,
                    start_date=template.start_date,
                    end_date=template.end_date,
                    tag_id=template.tag_id,
                    account_id=template.account_id,
                    credit_card_id=template.credit_card_id,
                    impact_policy=template.impact_policy,
                    auto_settle=template.auto_settle,
                    installment_group_id=(template.installment_group_id or template.id),
                    recurrence_series_id=(
                        template.recurrence_series_id
                        or template.installment_group_id
                        or template.id
                    ),
                    paid_at=None,
                )
            )
        return occurrences

    @staticmethod
    def _persist(created: list[Transaction]) -> int:
        if not created:
            logger.info("recurrence: no new occurrences to create")
            return 0

        try:
            db.session.add_all(created)
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception(
                "recurrence: failed to persist %d occurrence(s) — session rolled back",
                len(created),
            )
            raise

        logger.info("recurrence: created %d new occurrence(s)", len(created))
        return len(created)
