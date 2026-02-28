"""Runtime feature-flag helpers with local catalog fallback."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_CATALOG_FILE = Path(__file__).resolve().parents[2] / "config" / "feature-flags.json"
_ENABLED_STATUSES = {"active", "released", "enabled"}
_OVERRIDE_ENV = "AURAXIS_FEATURE_FLAGS"


def _normalize_status(value: object) -> str:
    return str(value or "").strip().lower()


def _as_bool_or_none(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


@lru_cache(maxsize=1)
def _load_catalog() -> dict[str, dict[str, Any]]:
    if not _CATALOG_FILE.exists():
        return {}

    payload = json.loads(_CATALOG_FILE.read_text(encoding="utf-8"))
    flags = payload.get("flags", [])
    if not isinstance(flags, list):
        return {}

    by_key: dict[str, dict[str, Any]] = {}
    for flag in flags:
        if not isinstance(flag, dict):
            continue
        key = str(flag.get("key", "")).strip()
        if not key:
            continue
        by_key[key] = flag
    return by_key


@lru_cache(maxsize=1)
def _load_overrides() -> dict[str, bool]:
    raw_payload = str(os.getenv(_OVERRIDE_ENV, "")).strip()
    if not raw_payload:
        return {}

    try:
        parsed = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, dict):
        return {}

    overrides: dict[str, bool] = {}
    for key, value in parsed.items():
        bool_value = _as_bool_or_none(value)
        if bool_value is None:
            continue
        overrides[str(key)] = bool_value
    return overrides


def refresh_feature_flag_state() -> None:
    """Clear in-memory caches for catalog and env overrides."""
    _load_catalog.cache_clear()
    _load_overrides.cache_clear()


def is_feature_enabled(
    flag_key: str,
    provider_value: bool | None = None,
) -> bool:
    """Resolve feature by provider decision, env override and local catalog."""
    provider_bool = _as_bool_or_none(provider_value)
    if provider_bool is not None:
        return provider_bool

    overrides = _load_overrides()
    if flag_key in overrides:
        return overrides[flag_key]

    catalog = _load_catalog()
    local_flag = catalog.get(flag_key, {})
    status = _normalize_status(local_flag.get("status"))
    return status in _ENABLED_STATUSES
