"""Tests for the daily insight lens rotation (#1654)."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from app.services.insight_angle_rotation import (
    INSIGHT_ANGLES,
    resolve_daily_angle,
)

_USER_A = UUID("11111111-1111-1111-1111-111111111111")


def test_same_user_and_day_always_resolve_to_the_same_angle() -> None:
    """Determinism is what makes the choice testable and explainable."""
    anchor = date(2026, 8, 1)

    first = resolve_daily_angle(_USER_A, anchor)
    second = resolve_daily_angle(_USER_A, anchor)

    assert first is second


def test_ten_consecutive_days_cover_every_angle_without_repeating() -> None:
    """The point of the rotation: ten days, ten different lenses."""
    anchor = date(2026, 8, 1)

    keys = [
        resolve_daily_angle(_USER_A, anchor + timedelta(days=offset)).key
        for offset in range(len(INSIGHT_ANGLES))
    ]

    assert len(set(keys)) == len(INSIGHT_ANGLES)


def test_consecutive_days_never_repeat_the_previous_angle() -> None:
    """Day N and day N+1 must not open on the same dimension."""
    anchor = date(2026, 8, 1)

    keys = [
        resolve_daily_angle(_USER_A, anchor + timedelta(days=offset)).key
        for offset in range(30)
    ]

    assert all(
        current != following for current, following in zip(keys, keys[1:], strict=False)
    )


def test_the_cycle_does_not_line_up_with_the_week() -> None:
    """Ten lenses over a seven-day week: same weekday, different lens."""
    anchor = date(2026, 8, 1)

    this_week = resolve_daily_angle(_USER_A, anchor).key
    next_week = resolve_daily_angle(_USER_A, anchor + timedelta(days=7)).key

    assert this_week != next_week


def test_the_lens_varies_across_users_on_the_same_day() -> None:
    """Without the per-user offset the whole base would share one lens a day.

    Two given users may of course collide — there are only ten lenses. What
    must not happen is the base moving as a single block, so this asserts on
    the spread rather than on one pair.
    """
    anchor = date(2026, 8, 1)
    users = [UUID(f"{index:032x}") for index in range(1, 21)]

    keys = {resolve_daily_angle(user, anchor).key for user in users}

    assert len(keys) >= 5


def test_accepts_a_string_user_id() -> None:
    """Callers hand over whatever the request carries; both shapes must work."""
    anchor = date(2026, 8, 1)

    assert resolve_daily_angle(str(_USER_A), anchor) is resolve_daily_angle(
        _USER_A, anchor
    )


def test_every_angle_carries_an_instruction() -> None:
    """An empty instruction would silently disable the rotation for that day."""
    assert all(angle.instruction.strip() for angle in INSIGHT_ANGLES)
    assert len({angle.key for angle in INSIGHT_ANGLES}) == len(INSIGHT_ANGLES)
