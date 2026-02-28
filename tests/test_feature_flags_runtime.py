from __future__ import annotations

import json

from app.utils import feature_flags


def test_feature_flag_uses_local_catalog_status() -> None:
    feature_flags.refresh_feature_flag_state()
    assert (
        feature_flags.is_feature_enabled("api.tools.salary-raise-calculator") is False
    )


def test_feature_flag_uses_provider_value_when_present() -> None:
    feature_flags.refresh_feature_flag_state()
    assert (
        feature_flags.is_feature_enabled(
            "api.tools.salary-raise-calculator",
            provider_value=True,
        )
        is True
    )


def test_feature_flag_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv(
        "AURAXIS_FEATURE_FLAGS",
        json.dumps({"api.tools.salary-raise-calculator": True}),
    )
    feature_flags.refresh_feature_flag_state()
    assert feature_flags.is_feature_enabled("api.tools.salary-raise-calculator") is True


def test_feature_flag_ignores_invalid_override_payload(monkeypatch) -> None:
    monkeypatch.setenv("AURAXIS_FEATURE_FLAGS", "{invalid")
    feature_flags.refresh_feature_flag_state()
    assert (
        feature_flags.is_feature_enabled("api.tools.salary-raise-calculator") is False
    )
