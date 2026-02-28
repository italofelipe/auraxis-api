"""Runtime feature-flag helpers with local catalog and Unleash fallback."""

from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib import error, request

_CATALOG_FILE = Path(__file__).resolve().parents[2] / "config" / "feature-flags.json"
_ENABLED_STATUSES = {"active", "released", "enabled"}
_OVERRIDE_ENV = "AURAXIS_FEATURE_FLAGS"
_PROVIDER_ENV = "AURAXIS_FLAG_PROVIDER"
_UNLEASH_URL_ENV = "AURAXIS_UNLEASH_URL"
_UNLEASH_API_TOKEN_ENV = "AURAXIS_UNLEASH_API_TOKEN"
_UNLEASH_APP_NAME_ENV = "AURAXIS_UNLEASH_APP_NAME"
_UNLEASH_INSTANCE_ID_ENV = "AURAXIS_UNLEASH_INSTANCE_ID"
_UNLEASH_ENVIRONMENT_ENV = "AURAXIS_UNLEASH_ENVIRONMENT"
_UNLEASH_TIMEOUT_ENV = "AURAXIS_UNLEASH_TIMEOUT_SECONDS"
_UNLEASH_CACHE_TTL_ENV = "AURAXIS_UNLEASH_CACHE_TTL_SECONDS"
_UNLEASH_ENDPOINT_PATH = "/api/client/features"
_UNLEASH_DEFAULT_TIMEOUT_SECONDS = 2.0
_UNLEASH_DEFAULT_CACHE_TTL_SECONDS = 30.0

_unleash_cache_snapshot: dict[str, bool] = {}
_unleash_cache_expire_at_seconds = 0.0


def _read_env_value(keys: tuple[str, ...], default_value: str = "") -> str:
    """Read env values using precedence order."""
    for key in keys:
        raw_value = os.getenv(key)
        if isinstance(raw_value, str):
            normalized = raw_value.strip()
            if normalized:
                return normalized
    return default_value


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


def _get_provider_mode() -> str:
    return _read_env_value((_PROVIDER_ENV,), "local").lower()


def _get_unleash_url() -> str:
    return _read_env_value(
        (_UNLEASH_URL_ENV, "AURAXIS_UNLEASH_PROXY_URL"),
        "",
    ).rstrip("/")


def _get_unleash_timeout_seconds() -> float:
    raw_timeout = str(
        os.getenv(_UNLEASH_TIMEOUT_ENV, str(_UNLEASH_DEFAULT_TIMEOUT_SECONDS)),
    ).strip()
    try:
        timeout_seconds = float(raw_timeout)
    except ValueError:
        return _UNLEASH_DEFAULT_TIMEOUT_SECONDS
    if timeout_seconds <= 0:
        return _UNLEASH_DEFAULT_TIMEOUT_SECONDS
    return timeout_seconds


def _get_unleash_cache_ttl_seconds() -> float:
    raw_ttl = str(
        os.getenv(_UNLEASH_CACHE_TTL_ENV, str(_UNLEASH_DEFAULT_CACHE_TTL_SECONDS)),
    ).strip()
    try:
        ttl_seconds = float(raw_ttl)
    except ValueError:
        return _UNLEASH_DEFAULT_CACHE_TTL_SECONDS
    if ttl_seconds <= 0:
        return _UNLEASH_DEFAULT_CACHE_TTL_SECONDS
    return ttl_seconds


def _build_unleash_headers() -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": "application/json",
        "UNLEASH-APPNAME": _read_env_value(
            (_UNLEASH_APP_NAME_ENV,),
            "auraxis-api",
        ),
        "UNLEASH-INSTANCEID": _read_env_value(
            (_UNLEASH_INSTANCE_ID_ENV,),
            "auraxis-api",
        ),
        "UNLEASH-ENVIRONMENT": _read_env_value(
            (_UNLEASH_ENVIRONMENT_ENV, "AURAXIS_RUNTIME_ENV"),
            "development",
        ),
    }
    api_token = _read_env_value(
        (_UNLEASH_API_TOKEN_ENV, "AURAXIS_UNLEASH_CLIENT_KEY"),
        "",
    )
    if api_token:
        headers["Authorization"] = api_token
    return headers


def _parse_unleash_payload(payload: object) -> dict[str, bool]:
    if not isinstance(payload, dict):
        return {}

    features = payload.get("features", [])
    if not isinstance(features, list):
        return {}

    parsed_flags: dict[str, bool] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue

        flag_name = str(feature.get("name", "")).strip()
        flag_enabled = feature.get("enabled")
        if flag_name and isinstance(flag_enabled, bool):
            parsed_flags[flag_name] = flag_enabled

    return parsed_flags


def _fetch_unleash_snapshot() -> dict[str, bool]:
    global _unleash_cache_expire_at_seconds
    global _unleash_cache_snapshot

    if _get_provider_mode() != "unleash":
        return {}

    unleash_url = _get_unleash_url()
    if not unleash_url:
        return {}

    now_seconds = time.monotonic()
    if now_seconds < _unleash_cache_expire_at_seconds:
        return _unleash_cache_snapshot

    request_url = f"{unleash_url}{_UNLEASH_ENDPOINT_PATH}"
    request_obj = request.Request(
        request_url,
        headers=_build_unleash_headers(),
        method="GET",
    )

    try:
        with request.urlopen(
            request_obj,
            timeout=_get_unleash_timeout_seconds(),
        ) as response:
            response_status = int(getattr(response, "status", 200))
            if response_status != 200:
                return {}
            payload = json.loads(response.read().decode("utf-8"))
    except (
        error.URLError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return {}

    parsed_flags = _parse_unleash_payload(payload)
    _unleash_cache_snapshot = parsed_flags
    _unleash_cache_expire_at_seconds = now_seconds + _get_unleash_cache_ttl_seconds()
    return parsed_flags


def resolve_provider_decision(flag_key: str) -> bool | None:
    """Resolve provider decision for a flag using Unleash-compatible endpoint."""
    snapshot = _fetch_unleash_snapshot()
    provider_value = snapshot.get(flag_key)
    if isinstance(provider_value, bool):
        return provider_value
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
    """Clear in-memory caches for provider, catalog and env overrides."""
    global _unleash_cache_expire_at_seconds
    global _unleash_cache_snapshot

    _load_catalog.cache_clear()
    _load_overrides.cache_clear()
    _unleash_cache_snapshot = {}
    _unleash_cache_expire_at_seconds = 0.0


def is_feature_enabled(
    flag_key: str,
    provider_value: bool | None = None,
) -> bool:
    """Resolve feature by provider decision, env override and local catalog."""
    provider_bool = _as_bool_or_none(provider_value)
    if provider_bool is not None:
        return provider_bool

    provider_decision = resolve_provider_decision(flag_key)
    if provider_decision is not None:
        return provider_decision

    overrides = _load_overrides()
    if flag_key in overrides:
        return overrides[flag_key]

    catalog = _load_catalog()
    local_flag = catalog.get(flag_key, {})
    status = _normalize_status(local_flag.get("status"))
    return status in _ENABLED_STATUSES
