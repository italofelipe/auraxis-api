"""
Tests for FeatureFlagService — covers set/get/list/delete, is_enabled canary
logic, NoOp fallback, and the singleton factory.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.cache_service import _NoOpCacheService
from app.services.feature_flag_service import (
    FeatureFlagConfig,
    FeatureFlagService,
    get_feature_flag_service,
    reset_feature_flag_service_for_tests,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_redis_client() -> MagicMock:
    """Return a mock Redis client with enough stubs for the service."""
    client = MagicMock()
    # scan returns (cursor=0, []) by default — overridden per test
    client.scan.return_value = (0, [])
    return client


def _make_redis_cache(client: MagicMock) -> MagicMock:
    """Return a mock RedisCacheService wrapping the given client."""
    cache = MagicMock()
    cache.available = True
    cache._client = client

    def _get(key: str):  # type: ignore[return]
        raw = client.get(key)
        if raw is None:
            return None
        decoded = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        return json.loads(decoded)

    cache.get.side_effect = _get
    return cache


def _flag_payload(**kwargs) -> bytes:  # type: ignore[return]
    defaults = {
        "enabled": True,
        "canary_percentage": 0,
        "description": "",
        "updated_at": "2026-04-01T00:00:00+00:00",
    }
    defaults.update(kwargs)
    return json.dumps(defaults).encode()


# ── FeatureFlagConfig ─────────────────────────────────────────────────────────


def test_feature_flag_config_from_dict_defaults() -> None:
    config = FeatureFlagConfig.from_dict({})
    assert config.enabled is False
    assert config.canary_percentage == 0
    assert config.description == ""


def test_feature_flag_config_to_dict_roundtrip() -> None:
    config = FeatureFlagConfig(
        enabled=True, canary_percentage=25, description="test", updated_at="now"
    )
    d = config.to_dict()
    restored = FeatureFlagConfig.from_dict(d)
    assert restored == config


# ── set_flag ──────────────────────────────────────────────────────────────────


def test_set_flag_stores_json_in_redis() -> None:
    client = _make_redis_client()
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        svc.set_flag("tools.fgts_simulator", enabled=True, canary_percentage=10)

    client.set.assert_called_once()
    call_key = client.set.call_args[0][0]
    call_value = client.set.call_args[0][1]
    assert call_key == "auraxis:flags:tools.fgts_simulator"
    parsed = json.loads(call_value)
    assert parsed["enabled"] is True
    assert parsed["canary_percentage"] == 10


def test_set_flag_raises_on_invalid_canary_percentage() -> None:
    client = _make_redis_client()
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        with pytest.raises(ValueError, match="canary_percentage"):
            svc.set_flag("flag", enabled=True, canary_percentage=101)


def test_set_flag_noop_when_redis_unavailable() -> None:
    noop_cache = _NoOpCacheService()

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=noop_cache
    ):
        svc = FeatureFlagService()
        # Must not raise
        svc.set_flag("flag", enabled=True)


# ── get_flag ──────────────────────────────────────────────────────────────────


def test_get_flag_returns_config_when_found() -> None:
    client = _make_redis_client()
    client.get.return_value = _flag_payload(enabled=True, canary_percentage=50)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        config = svc.get_flag("tools.split_bill")

    assert config is not None
    assert config.enabled is True
    assert config.canary_percentage == 50


def test_get_flag_returns_none_when_not_found() -> None:
    client = _make_redis_client()
    client.get.return_value = None
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        assert svc.get_flag("nonexistent") is None


def test_get_flag_returns_none_when_redis_unavailable() -> None:
    noop_cache = _NoOpCacheService()

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=noop_cache
    ):
        svc = FeatureFlagService()
        assert svc.get_flag("any.flag") is None


# ── list_flags ────────────────────────────────────────────────────────────────


def test_list_flags_returns_all_flags() -> None:
    client = _make_redis_client()
    flag_key = b"auraxis:flags:tools.cta_trial"
    client.scan.return_value = (0, [flag_key])
    client.get.return_value = _flag_payload(enabled=True, canary_percentage=0)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        flags = svc.list_flags()

    assert "tools.cta_trial" in flags
    assert flags["tools.cta_trial"].enabled is True


def test_list_flags_returns_empty_on_noop() -> None:
    noop_cache = _NoOpCacheService()

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=noop_cache
    ):
        svc = FeatureFlagService()
        assert svc.list_flags() == {}


# ── delete_flag ───────────────────────────────────────────────────────────────


def test_delete_flag_removes_key() -> None:
    client = _make_redis_client()
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        svc.delete_flag("tools.overtime_calculator")

    client.delete.assert_called_once_with("auraxis:flags:tools.overtime_calculator")


def test_delete_flag_noop_when_redis_unavailable() -> None:
    noop_cache = _NoOpCacheService()

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=noop_cache
    ):
        svc = FeatureFlagService()
        # Must not raise
        svc.delete_flag("flag")


# ── is_enabled ────────────────────────────────────────────────────────────────


def test_is_enabled_returns_true_when_fully_enabled() -> None:
    client = _make_redis_client()
    client.get.return_value = _flag_payload(enabled=True, canary_percentage=0)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        assert svc.is_enabled("flag", user_id="user-123") is True


def test_is_enabled_returns_false_when_disabled() -> None:
    client = _make_redis_client()
    client.get.return_value = _flag_payload(enabled=False, canary_percentage=0)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        assert svc.is_enabled("flag", user_id="user-123") is False


def test_is_enabled_returns_false_when_flag_not_found() -> None:
    client = _make_redis_client()
    client.get.return_value = None
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        assert svc.is_enabled("nonexistent") is False


def test_is_enabled_canary_0_percent_returns_true_for_all() -> None:
    """canary_percentage=0 means the flag is on for 100% of users."""
    client = _make_redis_client()
    client.get.return_value = _flag_payload(enabled=True, canary_percentage=0)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        assert svc.is_enabled("flag") is True


def test_is_enabled_canary_100_percent_returns_true_for_all() -> None:
    """canary_percentage=100 means the flag is on for all users."""
    client = _make_redis_client()
    client.get.return_value = _flag_payload(enabled=True, canary_percentage=100)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        # Any user_id should be True
        assert svc.is_enabled("flag", user_id="user-abc") is True


def test_is_enabled_canary_50_percent_is_deterministic() -> None:
    """At 50% canary, the same user always gets the same result."""
    client = _make_redis_client()
    client.get.return_value = _flag_payload(enabled=True, canary_percentage=50)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        flag_name = "flag"
        user_id = "stable-user-id"
        result_1 = svc.is_enabled(flag_name, user_id=user_id)
        result_2 = svc.is_enabled(flag_name, user_id=user_id)
        assert result_1 == result_2  # must be deterministic


def test_is_enabled_canary_50_percent_bucket_logic() -> None:
    """Directly verify bucket formula: hash(name:user_id) % 100 < percentage."""
    flag_name = "flag"
    user_id = "some-user"
    bucket = hash(f"{flag_name}:{user_id}") % 100
    expected = bucket < 50

    client = _make_redis_client()
    client.get.return_value = _flag_payload(enabled=True, canary_percentage=50)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        assert svc.is_enabled(flag_name, user_id=user_id) == expected


def test_is_enabled_canary_excludes_anonymous_users() -> None:
    """When canary is active (1-99%) and user_id is None, return False."""
    client = _make_redis_client()
    client.get.return_value = _flag_payload(enabled=True, canary_percentage=50)
    cache = _make_redis_cache(client)

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=cache
    ):
        svc = FeatureFlagService()
        assert svc.is_enabled("flag", user_id=None) is False


def test_is_enabled_returns_false_when_redis_unavailable() -> None:
    """NoOp cache (Redis down) must cause is_enabled to return False."""
    noop_cache = _NoOpCacheService()

    with patch(
        "app.services.feature_flag_service.get_cache_service", return_value=noop_cache
    ):
        svc = FeatureFlagService()
        assert svc.is_enabled("any.flag", user_id="user-x") is False


# ── Singleton factory ─────────────────────────────────────────────────────────


def test_get_feature_flag_service_returns_same_instance() -> None:
    reset_feature_flag_service_for_tests()
    svc1 = get_feature_flag_service()
    svc2 = get_feature_flag_service()
    assert svc1 is svc2
    reset_feature_flag_service_for_tests()


def test_reset_feature_flag_service_for_tests_creates_new_instance() -> None:
    reset_feature_flag_service_for_tests()
    svc1 = get_feature_flag_service()
    reset_feature_flag_service_for_tests()
    svc2 = get_feature_flag_service()
    assert svc1 is not svc2
    reset_feature_flag_service_for_tests()
