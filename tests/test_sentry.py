"""Unit tests for app/extensions/sentry.py.

All tests mock sentry_sdk.init to avoid real network calls and assert the
correct initialisation behaviour under different environment configurations.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_sentry():
    """Force a fresh import of the sentry extension module."""
    import app.extensions.sentry as mod

    importlib.reload(mod)
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sentry_not_initialised_when_dsn_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_sentry() must be a no-op when SENTRY_DSN is not set."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        mock_init.assert_not_called()


def test_sentry_not_initialised_when_dsn_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_sentry() must be a no-op when SENTRY_DSN is an empty string."""
    monkeypatch.setenv("SENTRY_DSN", "")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        mock_init.assert_not_called()


def test_sentry_not_initialised_when_dsn_is_whitespace_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_sentry() must be a no-op when SENTRY_DSN contains only whitespace."""
    monkeypatch.setenv("SENTRY_DSN", "   ")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        mock_init.assert_not_called()


def test_sentry_initialised_when_dsn_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_sentry() must call sentry_sdk.init exactly once when SENTRY_DSN is set."""
    fake_dsn = "https://public@sentry.example.io/1"
    monkeypatch.setenv("SENTRY_DSN", fake_dsn)
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTRY_TRACES_RATE", "0.5")
    monkeypatch.setenv("SENTRY_PROFILES_RATE", "0.2")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        mock_init.assert_called_once()


def test_sentry_init_receives_correct_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """sentry_sdk.init must be called with the exact DSN from the environment."""
    fake_dsn = "https://public@sentry.example.io/42"
    monkeypatch.setenv("SENTRY_DSN", fake_dsn)

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        _, kwargs = mock_init.call_args
        assert kwargs.get("dsn") == fake_dsn


def test_sentry_init_send_default_pii_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_default_pii must always be False to comply with LGPD."""
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.io/99")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        _, kwargs = mock_init.call_args
        assert kwargs.get("send_default_pii") is False


def test_sentry_init_flask_integration_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FlaskIntegration must be present in the integrations list."""
    from sentry_sdk.integrations.flask import FlaskIntegration

    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.io/77")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        _, kwargs = mock_init.call_args
        integrations = kwargs.get("integrations", [])
        types = [type(i) for i in integrations]
        assert FlaskIntegration in types


def test_sentry_init_sqlalchemy_integration_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SqlalchemyIntegration must be present in the integrations list."""
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.io/88")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        _, kwargs = mock_init.call_args
        integrations = kwargs.get("integrations", [])
        types = [type(i) for i in integrations]
        assert SqlalchemyIntegration in types


def test_sentry_init_traces_sample_rate_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """traces_sample_rate must reflect SENTRY_TRACES_RATE env var."""
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.io/55")
    monkeypatch.setenv("SENTRY_TRACES_RATE", "0.25")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        _, kwargs = mock_init.call_args
        assert kwargs.get("traces_sample_rate") == pytest.approx(0.25)


def test_sentry_init_release_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """release must carry SENTRY_RELEASE so events map to the deployed commit."""
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.io/56")
    monkeypatch.setenv("SENTRY_RELEASE", "e623e673a2fb94f5371a896889c9eb0e5bdac77a")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        _, kwargs = mock_init.call_args
        assert kwargs.get("release") == "e623e673a2fb94f5371a896889c9eb0e5bdac77a"


def test_sentry_init_release_is_none_when_env_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An absent SENTRY_RELEASE must become None, never the empty string.

    Sentry treats "" as a release literally named empty, which silently splits
    the issue stream instead of leaving events unversioned.
    """
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.io/57")
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        _, kwargs = mock_init.call_args
        assert kwargs.get("release") is None


def test_sentry_init_registers_before_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """before_send must be passed to sentry_sdk.init for quota protection."""
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.io/11")

    with patch("sentry_sdk.init") as mock_init:
        mod = _reload_sentry()
        mod.init_sentry()
        _, kwargs = mock_init.call_args
        assert callable(kwargs.get("before_send"))


def test_before_send_drops_4xx_http_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """before_send must return None for HTTP exceptions with status < 500."""
    monkeypatch.delenv("SENTRY_ERROR_RATE", raising=False)
    mod = _reload_sentry()

    class FakeHTTPException(Exception):
        code = 404

    hint = {"exc_info": (FakeHTTPException, FakeHTTPException(), None)}
    result = mod._before_send({}, hint)
    assert result is None


def test_before_send_keeps_5xx_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """before_send must forward HTTP exceptions with status >= 500."""
    monkeypatch.delenv("SENTRY_ERROR_RATE", raising=False)
    mod = _reload_sentry()

    class FakeServerError(Exception):
        code = 500

    hint = {"exc_info": (FakeServerError, FakeServerError(), None)}
    event: dict = {"message": "server error"}
    result = mod._before_send(event, hint)
    assert result == event


def test_before_send_keeps_unhandled_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """before_send must forward exceptions with no HTTP status code."""
    monkeypatch.delenv("SENTRY_ERROR_RATE", raising=False)
    mod = _reload_sentry()

    hint = {"exc_info": (ValueError, ValueError("oops"), None)}
    event: dict = {"message": "unhandled"}
    result = mod._before_send(event, hint)
    assert result == event


def test_before_send_samples_events_at_zero_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SENTRY_ERROR_RATE=0.0 must drop all events (after 4xx filter)."""
    monkeypatch.setenv("SENTRY_ERROR_RATE", "0.0")
    mod = _reload_sentry()

    hint: dict = {}
    results = [mod._before_send({"msg": "x"}, hint) for _ in range(20)]
    assert all(r is None for r in results)


def test_before_send_passes_all_events_at_full_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SENTRY_ERROR_RATE=1.0 (default) must forward all non-4xx events."""
    monkeypatch.setenv("SENTRY_ERROR_RATE", "1.0")
    mod = _reload_sentry()

    hint: dict = {}
    event: dict = {"message": "error"}
    results = [mod._before_send(event, hint) for _ in range(20)]
    assert all(r is not None for r in results)


# ---------------------------------------------------------------------------
# _resolve_traces_rate — env-aware auto-default
# ---------------------------------------------------------------------------


def test_resolve_traces_rate_dev_defaults_to_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In dev with no explicit SENTRY_TRACES_RATE, return 1.0 to capture all."""
    monkeypatch.delenv("SENTRY_TRACES_RATE", raising=False)
    mod = _reload_sentry()
    assert mod._resolve_traces_rate("dev") == 1.0


def test_resolve_traces_rate_staging_and_preview_default_to_half(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """staging and preview return 0.5 when no explicit override."""
    monkeypatch.delenv("SENTRY_TRACES_RATE", raising=False)
    mod = _reload_sentry()
    assert mod._resolve_traces_rate("staging") == 0.5
    assert mod._resolve_traces_rate("preview") == 0.5


def test_resolve_traces_rate_production_defaults_to_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production keeps baseline 0.0 — opt-in via explicit env."""
    monkeypatch.delenv("SENTRY_TRACES_RATE", raising=False)
    mod = _reload_sentry()
    assert mod._resolve_traces_rate("production") == 0.0
    assert mod._resolve_traces_rate("unknown") == 0.0


def test_resolve_traces_rate_explicit_env_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit SENTRY_TRACES_RATE overrides env-aware default."""
    monkeypatch.setenv("SENTRY_TRACES_RATE", "0.3")
    mod = _reload_sentry()
    # Even in dev (where default would be 1.0), explicit override wins.
    assert mod._resolve_traces_rate("dev") == 0.3
    assert mod._resolve_traces_rate("production") == 0.3


def test_resolve_traces_rate_empty_env_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty string SENTRY_TRACES_RATE falls back to env-aware default."""
    monkeypatch.setenv("SENTRY_TRACES_RATE", "")
    mod = _reload_sentry()
    assert mod._resolve_traces_rate("dev") == 1.0
    assert mod._resolve_traces_rate("production") == 0.0
