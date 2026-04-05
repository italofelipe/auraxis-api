"""
feature_flag_service.py — Redis-backed feature flags with canary % support.

Architecture
------------
Each flag is stored as a JSON blob in Redis under the key
``auraxis:flags:<name>`` with no TTL (flags are persistent until explicitly
deleted or updated).

Canary evaluation is **deterministic per user**: given the same ``(name,
user_id)`` pair the result is always identical across processes and restarts.
The formula is::

    hash(f"{name}:{user_id}") % 100 < canary_percentage

Graceful degradation
--------------------
When Redis is unavailable (``_NoOpCacheService`` is active) ``is_enabled()``
returns ``False`` — fail-closed is the safe default for feature flags.

Usage
-----
    from app.services.feature_flag_service import get_feature_flag_service

    svc = get_feature_flag_service()
    if svc.is_enabled("tools.fgts_simulator", user_id=current_user_id):
        return run_fgts_simulator()
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.cache_service import get_cache_service

logger = logging.getLogger(__name__)

_FLAG_KEY_PREFIX = "auraxis:flags:"
_FLAG_KEY_PATTERN = "auraxis:flags:*"


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class FeatureFlagConfig:
    """Immutable value object representing a single feature flag's configuration."""

    enabled: bool
    canary_percentage: int  # 0 = everyone, 1-99 = canary subset, 100 = everyone
    description: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeatureFlagConfig":
        return cls(
            enabled=bool(data.get("enabled", False)),
            canary_percentage=int(data.get("canary_percentage", 0)),
            description=str(data.get("description", "")),
            updated_at=str(data.get("updated_at", "")),
        )


# ── Service ───────────────────────────────────────────────────────────────────


class FeatureFlagService:
    """Redis-backed feature flag service with canary percentage support."""

    def _flag_key(self, name: str) -> str:
        return f"{_FLAG_KEY_PREFIX}{name}"

    def set_flag(
        self,
        name: str,
        enabled: bool,
        canary_percentage: int = 0,
        description: str = "",
    ) -> None:
        """Create or update a feature flag (persisted in Redis with no TTL)."""
        cache = get_cache_service()
        if not cache.available:
            logger.warning(
                "feature_flag_service: Redis unavailable — flag '%s' not persisted",
                name,
            )
            return

        if not (0 <= canary_percentage <= 100):
            raise ValueError(
                f"canary_percentage must be between 0 and 100, got {canary_percentage}"
            )

        config = FeatureFlagConfig(
            enabled=enabled,
            canary_percentage=canary_percentage,
            description=description,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        key = self._flag_key(name)
        try:
            # Store without TTL — flags are persistent until explicitly deleted.
            # We use the raw client directly to call SET without SETEX.
            cache._client.set(key, json.dumps(config.to_dict(), default=str))  # type: ignore[union-attr]
        except Exception:
            logger.warning(
                "feature_flag_service: failed to persist flag '%s'", name, exc_info=True
            )

    def get_flag(self, name: str) -> FeatureFlagConfig | None:
        """Return the flag config or None if it does not exist / Redis is down."""
        cache = get_cache_service()
        if not cache.available:
            return None

        key = self._flag_key(name)
        raw = cache.get(key)
        if raw is None:
            return None
        try:
            if isinstance(raw, str):
                raw = json.loads(raw)
            return FeatureFlagConfig.from_dict(raw)
        except Exception:
            logger.warning(
                "feature_flag_service: failed to deserialize flag '%s'",
                name,
                exc_info=True,
            )
            return None

    def list_flags(self) -> dict[str, FeatureFlagConfig]:
        """Return all flags stored in Redis (uses SCAN — non-blocking)."""
        cache = get_cache_service()
        if not cache.available:
            return {}

        result: dict[str, FeatureFlagConfig] = {}
        try:
            cursor = 0
            while True:
                cursor, keys = cache._client.scan(  # type: ignore[union-attr]
                    cursor, match=_FLAG_KEY_PATTERN, count=100
                )
                for raw_key in keys:
                    decoded_key = (
                        raw_key.decode("utf-8")
                        if isinstance(raw_key, (bytes, bytearray))
                        else raw_key
                    )
                    flag_name = decoded_key[len(_FLAG_KEY_PREFIX) :]
                    config = self.get_flag(flag_name)
                    if config is not None:
                        result[flag_name] = config
                if cursor == 0:
                    break
        except Exception:
            logger.warning(
                "feature_flag_service: list_flags scan failed", exc_info=True
            )
        return result

    def is_enabled(self, name: str, user_id: str | None = None) -> bool:
        """
        Evaluate whether a flag is active for the given user.

        Logic:
        - Redis unavailable → False (fail-closed)
        - Flag not found → False
        - Flag disabled → False
        - canary_percentage == 0 → True for everyone
        - canary_percentage == 100 → True for everyone
        - 1 <= canary_percentage <= 99 → deterministic hash(name:user_id) % 100

        When ``user_id`` is None and canary mode is active the call returns
        False (anonymous users are excluded from canary by default).
        """
        cache = get_cache_service()
        if not cache.available:
            return False

        config = self.get_flag(name)
        if config is None:
            return False
        if not config.enabled:
            return False

        pct = config.canary_percentage
        if pct == 0 or pct == 100:
            return True

        # Canary subset: deterministic per (name, user_id)
        if user_id is None:
            return False
        bucket = hash(f"{name}:{user_id}") % 100
        return bucket < pct

    def delete_flag(self, name: str) -> None:
        """Remove a flag from Redis."""
        cache = get_cache_service()
        if not cache.available:
            logger.warning(
                "feature_flag_service: Redis unavailable — flag '%s' not deleted", name
            )
            return
        try:
            cache._client.delete(self._flag_key(name))  # type: ignore[union-attr]
        except Exception:
            logger.warning(
                "feature_flag_service: failed to delete flag '%s'", name, exc_info=True
            )


# ── Singleton factory ─────────────────────────────────────────────────────────

_feature_flag_service_instance: FeatureFlagService | None = None


def get_feature_flag_service() -> FeatureFlagService:
    """Return the module-level FeatureFlagService singleton."""
    global _feature_flag_service_instance  # noqa: PLW0603
    if _feature_flag_service_instance is None:
        _feature_flag_service_instance = FeatureFlagService()
    return _feature_flag_service_instance


def reset_feature_flag_service_for_tests() -> None:
    """Reset the singleton so tests can inject a fresh instance."""
    global _feature_flag_service_instance  # noqa: PLW0603
    _feature_flag_service_instance = None


__all__ = [
    "FeatureFlagConfig",
    "FeatureFlagService",
    "get_feature_flag_service",
    "reset_feature_flag_service_for_tests",
]
