"""Entitlement service — J12 / H-PROD-01 (subscription state & entitlement enforcement).

Public surface
--------------
has_entitlement(user_id, feature_key) -> bool
require_entitlement(feature_key)       -> Flask decorator (403 on failure)
grant_entitlement(...)                 -> Entitlement
revoke_entitlement(user_id, feature_key) -> None
sync_entitlements_from_subscription(subscription) -> list[Entitlement]
activate_premium(user_id, expires_at) -> list[Entitlement]
deactivate_premium(user_id) -> None
check_access(user_id, feature) -> bool
"""

from __future__ import annotations

import functools
import logging
import math
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from flask import Response, jsonify
from flask_jwt_extended import verify_jwt_in_request

from app.config.plan_features import PLAN_FEATURES, PREMIUM_FEATURES
from app.extensions.database import db
from app.models.entitlement import Entitlement, EntitlementSource
from app.models.subscription import Subscription, SubscriptionStatus
from app.services.cache_service import ENTITLEMENT_CACHE_TTL, get_cache_service
from app.utils.datetime_utils import utc_now_naive

logger = logging.getLogger(__name__)

_ENTITLEMENT_KEY_PREFIX = "entitlement"


def _entitlement_cache_key(user_id: str | UUID, feature_key: str) -> str:
    return f"{_ENTITLEMENT_KEY_PREFIX}:{user_id}:{feature_key}"


def _entitlement_user_pattern(user_id: str | UUID) -> str:
    return f"{_ENTITLEMENT_KEY_PREFIX}:{user_id}:*"


def _invalidate_entitlement_cache(user_id: str | UUID) -> None:
    """Invalidate all cached entitlement checks for *user_id*."""
    try:
        get_cache_service().invalidate_pattern(_entitlement_user_pattern(user_id))
    except Exception:
        logger.warning(
            "entitlement_cache: invalidate_pattern failed for user_id=%s", user_id
        )


# ---------------------------------------------------------------------------
# Core query
# ---------------------------------------------------------------------------


def has_entitlement(user_id: str | UUID, feature_key: str) -> bool:
    """Return True when *user_id* holds a non-expired entitlement for *feature_key*.

    Results are cached in Redis for ``ENTITLEMENT_CACHE_TTL`` seconds and
    invalidated whenever an entitlement is granted, revoked, or synced.  When
    Redis is unavailable the function falls through to the database query so
    that a cache outage never incorrectly blocks a legitimate user.
    """
    try:
        from app.services.subscription_service import (
            ensure_premium_override_subscription,
            is_premium_override_user_id,
        )

        normalized_user_id = UUID(str(user_id))
        if is_premium_override_user_id(normalized_user_id):
            ensure_premium_override_subscription(normalized_user_id)
    except (TypeError, ValueError):
        pass

    from app.services.premium_override_service import get_active_premium_override

    now = utc_now_naive()
    premium_override = (
        get_active_premium_override(user_id, now=now)
        if feature_key in PREMIUM_FEATURES
        else None
    )
    cache = get_cache_service()
    cache_key = _entitlement_cache_key(user_id, feature_key)

    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)

    ent = (
        Entitlement.query.filter_by(
            user_id=user_id,
            feature_key=feature_key,
        )
        .filter((Entitlement.expires_at.is_(None)) | (Entitlement.expires_at > now))
        .first()
    )
    result = premium_override is not None or ent is not None
    expirations = [
        candidate
        for candidate in (
            premium_override.expires_at if premium_override else None,
            ent.expires_at if ent else None,
        )
        if candidate is not None
    ]
    ttl = ENTITLEMENT_CACHE_TTL
    if expirations:
        ttl = max(1, min(ttl, math.ceil((min(expirations) - now).total_seconds())))
    cache.set(cache_key, result, ttl=ttl)
    return result


# ---------------------------------------------------------------------------
# Flask route decorator
# ---------------------------------------------------------------------------


def require_entitlement(feature_key: str) -> Any:
    """Flask route decorator — returns 403 JSON when user lacks entitlement.

    Must be applied after ``@jwt_required()`` so that a valid JWT is already
    in scope.

    Example::

        @app.route("/export")
        @jwt_required()
        @require_entitlement("export_pdf")
        def export_pdf():
            ...
    """

    def decorator(fn: Any) -> Any:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            verify_jwt_in_request()
            from app.auth import current_user_id as _current_user_id

            uid = _current_user_id()
            if not has_entitlement(uid, feature_key):
                _msg = f"Feature '{feature_key}' requires an active entitlement."
                body: Response = jsonify(
                    {
                        "success": False,
                        "message": _msg,
                        "error": {
                            "code": "ENTITLEMENT_REQUIRED",
                            "message": _msg,
                        },
                    }
                )
                body.status_code = 403
                return body
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def grant_entitlement(
    user_id: str | UUID,
    feature_key: str,
    source: str,
    expires_at: datetime | None = None,
) -> Entitlement:
    """Create or update an entitlement for *(user_id, feature_key)*.

    If an entitlement already exists (regardless of expiry) it is updated in
    place rather than creating a duplicate row.
    """
    try:
        source_enum = EntitlementSource(source)
    except ValueError:
        source_enum = EntitlementSource.MANUAL

    existing = Entitlement.query.filter_by(
        user_id=user_id, feature_key=feature_key
    ).first()

    if existing is not None:
        existing.source = source_enum
        existing.expires_at = expires_at
        existing.granted_at = utc_now_naive()
        db.session.flush()
        _invalidate_entitlement_cache(user_id)
        return cast(Entitlement, existing)

    ent = Entitlement(
        user_id=user_id,
        feature_key=feature_key,
        source=source_enum,
        expires_at=expires_at,
    )
    db.session.add(ent)
    db.session.flush()
    _invalidate_entitlement_cache(user_id)
    return ent


def revoke_entitlement(user_id: str | UUID, feature_key: str) -> None:
    """Delete the entitlement row for *(user_id, feature_key)* if it exists."""
    Entitlement.query.filter_by(user_id=user_id, feature_key=feature_key).delete(
        synchronize_session="fetch"
    )
    db.session.flush()
    _invalidate_entitlement_cache(user_id)


# ---------------------------------------------------------------------------
# Subscription-driven sync
# ---------------------------------------------------------------------------


_DEGRADED_STATUSES = {
    SubscriptionStatus.CANCELED,
    SubscriptionStatus.EXPIRED,
    SubscriptionStatus.PAST_DUE,
}


def _resolve_effective_plan(plan_slug: str, status: SubscriptionStatus | None) -> str:
    if status in _DEGRADED_STATUSES:
        return "free"
    return plan_slug if plan_slug in PLAN_FEATURES else "free"


def _resolve_entitlement_source(
    effective_plan: str,
    status: SubscriptionStatus | None,
) -> EntitlementSource:
    if effective_plan == "trial" or status == SubscriptionStatus.TRIALING:
        return EntitlementSource.TRIAL
    return EntitlementSource.SUBSCRIPTION


def sync_entitlements_from_subscription(
    subscription: Subscription,
) -> list[Entitlement]:
    """Grant/revoke feature entitlements driven by *subscription*.

    Rules
    -----
    - ``premium`` or ``trial`` plan → grant all PLAN_FEATURES entries.
    - ``free`` plan, or status in {CANCELED, EXPIRED, PAST_DUE} → revoke premium-only
      features, keep free-tier features.
    - Always normalises existing entitlements: unknown features for the plan
      are removed, missing ones are added.

    Returns the full list of active entitlements after the sync.
    """
    user_id = subscription.user_id
    plan_slug = subscription.plan_code or "free"
    status = subscription.status

    effective_plan = _resolve_effective_plan(plan_slug, status)
    desired_features: set[str] = set(PLAN_FEATURES[effective_plan])
    source = _resolve_entitlement_source(effective_plan, status)

    # Fetch current entitlements that were granted by subscription/trial sources
    # (manual entitlements are intentionally left untouched)
    managed_sources = {EntitlementSource.SUBSCRIPTION, EntitlementSource.TRIAL}
    existing: list[Entitlement] = Entitlement.query.filter(
        Entitlement.user_id == user_id,
        Entitlement.source.in_(managed_sources),
    ).all()

    existing_keys: set[str] = {e.feature_key for e in existing}

    # Revoke features no longer in the desired set
    for feature_key in existing_keys - desired_features:
        revoke_entitlement(user_id, feature_key)
        logger.info(
            "Revoked entitlement user=%s feature=%s (plan=%s status=%s)",
            user_id,
            feature_key,
            effective_plan,
            status.value if status else "unknown",
        )

    # Grant missing features
    for feature_key in desired_features - existing_keys:
        grant_entitlement(
            user_id=user_id,
            feature_key=feature_key,
            source=source.value,
            expires_at=subscription.current_period_end,
        )
        logger.info(
            "Granted entitlement user=%s feature=%s (plan=%s)",
            user_id,
            feature_key,
            effective_plan,
        )

    # Also update expires_at on already-existing managed entitlements
    for ent in existing:
        if ent.feature_key in desired_features:
            ent.expires_at = subscription.current_period_end
            ent.source = source

    db.session.flush()
    _invalidate_entitlement_cache(user_id)

    # Return full active list (managed + manual)
    return list(
        Entitlement.query.filter_by(user_id=user_id)
        .filter(
            (Entitlement.expires_at.is_(None))
            | (Entitlement.expires_at > utc_now_naive())
        )
        .all()
    )


# ---------------------------------------------------------------------------
# H-PROD-01 convenience wrappers (Asaas billing integration)
# ---------------------------------------------------------------------------


def activate_premium(
    user_id: str | UUID,
    expires_at: datetime | None = None,
) -> list[Entitlement]:
    """Grant all premium feature entitlements to *user_id*.

    Creates or refreshes each entitlement in PLAN_FEATURES["premium"].
    Returns the resulting list of active entitlements for the user.

    This is a convenience wrapper that does NOT require a Subscription record —
    useful for webhook-driven activation where we want to be resilient against
    missing subscription rows.
    """
    from app.config.plan_features import PLAN_FEATURES

    features = PLAN_FEATURES.get("premium", [])
    for feature_key in features:
        grant_entitlement(
            user_id=user_id,
            feature_key=feature_key,
            source=EntitlementSource.SUBSCRIPTION.value,
            expires_at=expires_at,
        )
    db.session.commit()
    _invalidate_entitlement_cache(user_id)

    now = utc_now_naive()
    return list(
        Entitlement.query.filter_by(user_id=user_id)
        .filter((Entitlement.expires_at.is_(None)) | (Entitlement.expires_at > now))
        .all()
    )


def deactivate_premium(user_id: str | UUID) -> None:
    """Revoke all premium-only feature entitlements for *user_id*.

    Free-tier features are left intact.  Commits the session.
    """
    from app.config.plan_features import PLAN_FEATURES, PREMIUM_FEATURES

    _ = PLAN_FEATURES  # imported for completeness; PREMIUM_FEATURES is the set we need
    for feature_key in PREMIUM_FEATURES:
        revoke_entitlement(user_id, feature_key)
    db.session.commit()
    _invalidate_entitlement_cache(user_id)


def check_access(user_id: str | UUID, feature: str) -> bool:
    """Return True when *user_id* may access *feature*.

    Checks both a live entitlement row *and* the trial window on the user's
    Subscription record, so callers do not need to join two tables.
    """
    if has_entitlement(user_id, feature):
        return True

    # Secondary check: active trial period on subscription record
    from app.models.subscription import Subscription, SubscriptionStatus

    now = utc_now_naive()
    sub: Subscription | None = Subscription.query.filter_by(user_id=user_id).first()
    if sub is None:
        return False
    if sub.status == SubscriptionStatus.TRIALING and sub.trial_ends_at is not None:
        return bool(sub.trial_ends_at > now)
    return False


# ---------------------------------------------------------------------------
# Legacy class-based API (kept for J7-1 compatibility)
# ---------------------------------------------------------------------------


class EntitlementService:
    """Thin wrapper retained for any existing callers from J7-1."""

    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id

    def list_entitlements(self) -> list[Entitlement]:
        from app.services.subscription_service import (
            ensure_premium_override_subscription,
            is_premium_override_user_id,
        )

        if is_premium_override_user_id(self.user_id):
            ensure_premium_override_subscription(self.user_id)
        now = utc_now_naive()
        return list(
            Entitlement.query.filter_by(user_id=self.user_id)
            .filter((Entitlement.expires_at.is_(None)) | (Entitlement.expires_at > now))
            .all()
        )

    def check_entitlement(self, feature_key: str) -> bool:
        return has_entitlement(self.user_id, feature_key)
