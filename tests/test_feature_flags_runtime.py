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


def test_feature_flag_uses_unleash_provider_snapshot(monkeypatch) -> None:
    class FakeUnleashResponse:
        status = 200

        def __enter__(self) -> "FakeUnleashResponse":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            payload = {
                "features": [
                    {
                        "name": "api.tools.salary-raise-calculator",
                        "enabled": True,
                    },
                ],
            }
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setenv("AURAXIS_FLAG_PROVIDER", "unleash")
    monkeypatch.setenv("AURAXIS_UNLEASH_URL", "https://flags.local")
    monkeypatch.setattr(
        feature_flags.request,
        "urlopen",
        lambda _req, timeout=0: FakeUnleashResponse(),
    )
    feature_flags.refresh_feature_flag_state()

    assert (
        feature_flags.resolve_provider_decision(
            "api.tools.salary-raise-calculator",
        )
        is True
    )
    assert feature_flags.is_feature_enabled("api.tools.salary-raise-calculator") is True


def test_feature_flag_ignores_unleash_provider_failure(monkeypatch) -> None:
    monkeypatch.setenv("AURAXIS_FLAG_PROVIDER", "unleash")
    monkeypatch.setenv("AURAXIS_UNLEASH_URL", "https://flags.local")
    monkeypatch.setattr(
        feature_flags.request,
        "urlopen",
        lambda _req, timeout=0: (_ for _ in ()).throw(
            feature_flags.error.URLError("network-error"),
        ),
    )
    feature_flags.refresh_feature_flag_state()

    assert (
        feature_flags.is_feature_enabled("api.tools.salary-raise-calculator") is False
    )


def test_feature_flag_uses_runtime_env_as_unleash_environment_header(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AURAXIS_RUNTIME_ENV", "staging")
    monkeypatch.delenv("AURAXIS_UNLEASH_ENVIRONMENT", raising=False)

    headers = feature_flags._build_unleash_headers()
    assert headers["UNLEASH-ENVIRONMENT"] == "staging"
