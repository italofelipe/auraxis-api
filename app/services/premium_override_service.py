"""Application helpers for manual premium access overrides."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from app.extensions.database import db
from app.models.premium_override import PremiumOverride
from app.utils.datetime_utils import utc_now_naive


def get_active_premium_override(
    user_id: str | UUID,
    *,
    now: datetime | None = None,
) -> PremiumOverride | None:
    override = cast(
        PremiumOverride | None,
        PremiumOverride.query.filter_by(user_id=user_id).first(),
    )
    if override is None or not override.is_active_at(now):
        return None
    return override


def has_active_premium_override(user_id: str | UUID) -> bool:
    return get_active_premium_override(user_id) is not None


def grant_premium_override(
    *,
    user_id: UUID,
    reason: str,
    granted_by: str,
    expires_at: datetime | None = None,
) -> PremiumOverride:
    if expires_at is not None and expires_at <= utc_now_naive():
        raise ValueError("expires_at must be in the future")
    override = cast(
        PremiumOverride | None,
        PremiumOverride.query.filter_by(user_id=user_id).first(),
    )
    if override is None:
        override = PremiumOverride(user_id=user_id)
        db.session.add(override)
    override.granted_at = utc_now_naive()
    override.expires_at = expires_at
    override.revoked_at = None
    override.reason = reason
    override.granted_by = granted_by
    override.revoked_reason = None
    override.revoked_by = None
    db.session.flush()
    _invalidate_entitlements(user_id)
    return override


def revoke_premium_override(
    *,
    user_id: UUID,
    reason: str,
    revoked_by: str,
) -> PremiumOverride | None:
    override = cast(
        PremiumOverride | None,
        PremiumOverride.query.filter_by(user_id=user_id).first(),
    )
    if override is None or override.revoked_at is not None:
        return override
    override.revoked_at = utc_now_naive()
    override.revoked_reason = reason
    override.revoked_by = revoked_by
    db.session.flush()
    _invalidate_entitlements(user_id)
    return override


def _invalidate_entitlements(user_id: UUID) -> None:
    from app.services.entitlement_service import _invalidate_entitlement_cache

    _invalidate_entitlement_cache(user_id)


__all__ = [
    "get_active_premium_override",
    "grant_premium_override",
    "has_active_premium_override",
    "revoke_premium_override",
]
