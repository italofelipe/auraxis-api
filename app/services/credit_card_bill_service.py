"""Credit card bill cycle + utilization service.

Pure helpers for determining a credit card's open bill cycle (start, end, due
date, status) given the cardholder's configured closing/due days, and for
computing how much of the card's limit is currently committed in a cycle.

The bill cycle math is anchored to a `date` so callers can ask for past or
future cycles by passing a non-today anchor. This keeps the function pure and
testable.

Utilization aggregates expense transactions in the open cycle window, including
`pending`, `overdue`, and `paid`. `cancelled` and `postponed` are excluded.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_

from app.extensions.database import db
from app.models.credit_card import CreditCard
from app.models.transaction import Transaction, TransactionStatus, TransactionType

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import ColumnElement

BillCycleStatus = Literal["open", "closed", "paid"]


@dataclass(frozen=True)
class BillCycle:
    """A single billing cycle for a credit card.

    - `start_date`: first day of the cycle (day after previous closing).
    - `end_date`: closing day — last day charges can post.
    - `due_date`: payment deadline for the cycle.
    - `status`: open while charges can still post, closed after end_date,
      paid only when caller has confirmed payment externally.
    """

    start_date: date
    end_date: date
    due_date: date
    status: BillCycleStatus


@dataclass(frozen=True)
class BillSummary:
    """Aggregated view of a cycle's transactions."""

    cycle: BillCycle
    transactions: list[Transaction]
    total_amount: Decimal
    paid_amount: Decimal
    pending_amount: Decimal


@dataclass(frozen=True)
class Utilization:
    """Snapshot of how much of a card's limit is committed in the open cycle."""

    cycle: BillCycle
    committed_amount: Decimal
    available_amount: Decimal | None
    limit_amount: Decimal | None
    utilization_pct: float | None


def _validate_day(label: str, value: int) -> None:
    if not 1 <= value <= 31:
        raise ValueError(f"{label} must be between 1 and 31 (got {value})")


def _safe_date(year: int, month: int, day: int) -> date:
    """Build a date clamping `day` to the month's last valid day.

    A card configured to close/due on day 30 or 31 still has a well-defined
    cycle boundary in short months: e.g. day 30 in February resolves to the
    28th (or 29th in a leap year). This avoids `date()` raising for days that
    do not exist in the target month.
    """
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    """Return (year, month) after shifting by `offset` months."""
    zero_based = (month - 1) + offset
    new_year = year + zero_based // 12
    new_month = (zero_based % 12) + 1
    return new_year, new_month


def compute_bill_cycle(*, closing_day: int, due_day: int, anchor: date) -> BillCycle:
    """Return the bill cycle that `anchor` belongs to.

    - When `anchor.day` <= `closing_day`, the anchor is inside the cycle ending
      on `closing_day` of `anchor`'s month.
    - When `anchor.day` > `closing_day`, the anchor is inside the cycle ending
      on `closing_day` of the FOLLOWING month.
    - `due_date` is the next `due_day` that occurs at or after `end_date`. When
      `due_day` < `closing_day`, the due date rolls to the next month.

    Status:
    - "open" while `anchor` <= `end_date`.
    - "closed" while `end_date` < `anchor` <= `due_date`.
    - "paid" once `anchor` > `due_date` (caller may override based on payment
      state when known).
    """
    _validate_day("closing_day", closing_day)
    _validate_day("due_day", due_day)

    if anchor.day <= closing_day:
        end_year, end_month = anchor.year, anchor.month
    else:
        end_year, end_month = _shift_month(anchor.year, anchor.month, 1)

    end_date = _safe_date(end_year, end_month, closing_day)

    prev_year, prev_month = _shift_month(end_year, end_month, -1)
    prev_close = _safe_date(prev_year, prev_month, closing_day)
    start_date = prev_close + timedelta(days=1)

    if due_day > closing_day:
        due_year, due_month = end_year, end_month
    else:
        due_year, due_month = _shift_month(end_year, end_month, 1)
    due_date = _safe_date(due_year, due_month, due_day)

    if anchor <= end_date:
        status: BillCycleStatus = "open"
    elif anchor <= due_date:
        status = "closed"
    else:
        status = "paid"

    return BillCycle(
        start_date=start_date,
        end_date=end_date,
        due_date=due_date,
        status=status,
    )


def bill_month_for(*, due_date: date, closing_day: int, due_day: int) -> str:
    """Return the ``YYYY-MM`` of the bill cycle that contains ``due_date``.

    A credit-card purchase belongs to the cycle that closes on ``closing_day``;
    the month it is billed in is the month that cycle CLOSES in (its
    ``end_date``). A purchase after the closing day rolls into the following
    month's bill; on or before closing it stays in the current month.
    """
    cycle = compute_bill_cycle(
        closing_day=closing_day,
        due_day=due_day,
        anchor=due_date,
    )
    return f"{cycle.end_date.year:04d}-{cycle.end_date.month:02d}"


def month_span_if_full_calendar_month(
    start_date: date | None, end_date: date | None
) -> str | None:
    """Return ``YYYY-MM`` when ``[start_date, end_date]`` is one whole month.

    The range covers exactly one calendar month when it starts on the first
    day, ends on that month's last day, and both endpoints share the same year
    and month. Otherwise (partial range, cross-month range, or a missing
    endpoint) returns ``None``.
    """
    if start_date is None or end_date is None:
        return None
    if start_date.day != 1:
        return None
    if (start_date.year, start_date.month) != (end_date.year, end_date.month):
        return None
    last_day = calendar.monthrange(end_date.year, end_date.month)[1]
    if end_date.day != last_day:
        return None
    return f"{start_date.year:04d}-{start_date.month:02d}"


def _calendar_month_bounds(month: str) -> tuple[date, date]:
    """Return the (first_day, last_day) calendar bounds for a ``YYYY-MM``."""
    try:
        year_str, month_str = month.split("-", 1)
        year = int(year_str)
        m = int(month_str)
        if not 1 <= m <= 12:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"month must be in YYYY-MM format (got {month!r})") from exc
    last_day = calendar.monthrange(year, m)[1]
    return date(year, m, 1), date(year, m, last_day)


def build_competence_month_filter(user_id: UUID, month: str) -> ColumnElement[bool]:
    """Build a SQLAlchemy predicate grouping transactions by competence month.

    For the calendar month ``month`` (``YYYY-MM``):

    - Non-card transactions (``credit_card_id IS NULL``) match when their
      ``due_date`` falls in the calendar month.
    - For each credit card owned by ``user_id``, its transactions match when
      ``due_date`` falls inside the bill cycle that CLOSES in ``month``
      (anchored on the card's ``closing_day`` for that month). Cards missing
      ``closing_day``/``due_day`` fall back to the calendar month.

    The returned predicate is meant to replace a raw ``due_date BETWEEN
    start AND end`` filter on a query already scoped to ``user_id``. It does
    not itself scope by user, so callers must keep their own ``user_id``
    filter.
    """
    month_start, month_end = _calendar_month_bounds(month)

    non_card = and_(
        Transaction.credit_card_id.is_(None),
        Transaction.due_date >= month_start,
        Transaction.due_date <= month_end,
    )

    branches: list[ColumnElement[bool]] = [non_card]

    cards = CreditCard.query.filter_by(user_id=user_id).all()
    for card in cards:
        if card.closing_day is None or card.due_day is None:
            cycle_start, cycle_end = month_start, month_end
        else:
            anchor = _safe_date(month_start.year, month_start.month, card.closing_day)
            cycle = compute_bill_cycle(
                closing_day=card.closing_day,
                due_day=card.due_day,
                anchor=anchor,
            )
            cycle_start, cycle_end = cycle.start_date, cycle.end_date
        branches.append(
            and_(
                Transaction.credit_card_id == card.id,
                Transaction.due_date >= cycle_start,
                Transaction.due_date <= cycle_end,
            )
        )

    return or_(*branches)


_COMMITTED_STATUSES = (
    TransactionStatus.PENDING,
    TransactionStatus.OVERDUE,
    TransactionStatus.PAID,
)


def compute_utilization(card: CreditCard, *, today: date) -> Utilization:
    """Return the card's open-cycle utilization snapshot.

    Sums expense transactions in the current open cycle whose status is
    one of {pending, overdue, paid}. `cancelled` and `postponed` are
    excluded.

    When the card has no `limit_amount` configured, `utilization_pct` and
    `available_amount` are returned as `None`.
    """
    if card.closing_day is None or card.due_day is None:
        raise ValueError(
            "card must have closing_day and due_day set before computing utilization"
        )

    cycle = compute_bill_cycle(
        closing_day=card.closing_day,
        due_day=card.due_day,
        anchor=today,
    )

    committed_raw = (
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0))
        .filter(
            and_(
                Transaction.credit_card_id == card.id,
                Transaction.deleted.is_(False),
                Transaction.type == TransactionType.EXPENSE,
                Transaction.status.in_(_COMMITTED_STATUSES),
                Transaction.due_date >= cycle.start_date,
                Transaction.due_date <= cycle.end_date,
            )
        )
        .scalar()
        or 0
    )
    committed = Decimal(committed_raw)

    limit_amount: Decimal | None = (
        Decimal(card.limit_amount) if card.limit_amount is not None else None
    )

    if limit_amount is None:
        available: Decimal | None = None
        pct: float | None = None
    else:
        available = limit_amount - committed
        if limit_amount == 0:
            pct = None
        else:
            pct = float(round((committed / limit_amount) * 100, 1))

    return Utilization(
        cycle=cycle,
        committed_amount=committed,
        available_amount=available,
        limit_amount=limit_amount,
        utilization_pct=pct,
    )


def compute_bill(card: CreditCard, *, month: str, today: date) -> BillSummary:
    """Return the bill (transactions + totals) for a specific YYYY-MM month.

    The month identifies which cycle to fetch: it represents the month the
    cycle CLOSES in. So month="2026-05" returns the cycle ending on
    `closing_day` of May 2026.
    """
    if card.closing_day is None or card.due_day is None:
        raise ValueError(
            "card must have closing_day and due_day set before computing bill"
        )

    try:
        year_str, month_str = month.split("-", 1)
        year = int(year_str)
        m = int(month_str)
        if not 1 <= m <= 12:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"month must be in YYYY-MM format (got {month!r})") from exc

    anchor_for_cycle = _safe_date(year, m, card.closing_day)
    cycle = compute_bill_cycle(
        closing_day=card.closing_day,
        due_day=card.due_day,
        anchor=anchor_for_cycle,
    )
    # Status reflects "today" relative to the requested cycle.
    if today <= cycle.end_date:
        status: BillCycleStatus = "open"
    elif today <= cycle.due_date:
        status = "closed"
    else:
        status = "paid"
    cycle = BillCycle(
        start_date=cycle.start_date,
        end_date=cycle.end_date,
        due_date=cycle.due_date,
        status=status,
    )

    transactions = (
        Transaction.query.filter(
            Transaction.credit_card_id == card.id,
            Transaction.deleted.is_(False),
            Transaction.due_date >= cycle.start_date,
            Transaction.due_date <= cycle.end_date,
        )
        .order_by(Transaction.due_date.asc())
        .all()
    )

    paid = Decimal(0)
    pending = Decimal(0)
    for tx in transactions:
        if tx.type != TransactionType.EXPENSE:
            continue
        if tx.status == TransactionStatus.PAID:
            paid += Decimal(tx.amount)
        elif tx.status in (TransactionStatus.PENDING, TransactionStatus.OVERDUE):
            pending += Decimal(tx.amount)
    total = paid + pending

    return BillSummary(
        cycle=cycle,
        transactions=transactions,
        total_amount=total,
        paid_amount=paid,
        pending_amount=pending,
    )
