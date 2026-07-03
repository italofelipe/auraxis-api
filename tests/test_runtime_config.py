from __future__ import annotations

import importlib
import logging

import config as config_module


def _reload_config_module():
    return importlib.reload(config_module)


def test_config_debug_defaults_to_false_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    module = _reload_config_module()
    assert module.Config.DEBUG is False


def test_validate_security_configuration_rejects_debug_in_production(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SECURITY_ENFORCE_STRONG_SECRETS", "true")
    monkeypatch.setenv("AURAXIS_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "false")
    module = _reload_config_module()

    try:
        module.validate_security_configuration()
        raise AssertionError("Expected RuntimeError for debug mode in production.")
    except RuntimeError as exc:
        assert "FLASK_DEBUG must be false in production" in str(exc)


def test_validate_security_configuration_allows_debug_outside_production(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SECURITY_ENFORCE_STRONG_SECRETS", "true")
    monkeypatch.setenv("AURAXIS_ENV", "dev")
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "false")
    module = _reload_config_module()

    module.validate_security_configuration()


def test_validate_security_configuration_rejects_weak_secrets_in_secure_runtime(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SECURITY_ENFORCE_STRONG_SECRETS", "true")
    monkeypatch.setenv("AURAXIS_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "false")
    monkeypatch.setenv("FLASK_TESTING", "false")
    monkeypatch.setenv("SECRET_KEY", "dev")
    monkeypatch.setenv("JWT_SECRET_KEY", "super-secret-key")
    module = _reload_config_module()

    try:
        module.validate_security_configuration()
        raise AssertionError("Expected RuntimeError for weak secrets.")
    except RuntimeError as exc:
        assert "Weak/invalid secrets" in str(exc)


def test_validate_security_configuration_rejects_disabled_enforcement_in_secure_runtime(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SECURITY_ENFORCE_STRONG_SECRETS", "false")
    monkeypatch.setenv("AURAXIS_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "false")
    monkeypatch.setenv("FLASK_TESTING", "false")
    monkeypatch.setenv("SECRET_KEY", "dev")
    monkeypatch.setenv("JWT_SECRET_KEY", "super-secret-key")
    module = _reload_config_module()

    try:
        module.validate_security_configuration()
        raise AssertionError(
            "Expected RuntimeError for disabled secret enforcement in secure runtime."
        )
    except RuntimeError as exc:
        assert "SECURITY_ENFORCE_STRONG_SECRETS must be true" in str(exc)


def test_validate_security_configuration_can_be_disabled_in_debug_runtime(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SECURITY_ENFORCE_STRONG_SECRETS", "false")
    monkeypatch.setenv("AURAXIS_ENV", "dev")
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "false")
    monkeypatch.setenv("SECRET_KEY", "dev")
    monkeypatch.setenv("JWT_SECRET_KEY", "super-secret-key")
    module = _reload_config_module()

    module.validate_security_configuration()


def _secure_runtime_with_strong_secrets(monkeypatch) -> None:
    monkeypatch.setenv("SECURITY_ENFORCE_STRONG_SECRETS", "true")
    monkeypatch.setenv("AURAXIS_ENV", "production")
    monkeypatch.setenv("FLASK_DEBUG", "false")
    monkeypatch.setenv("FLASK_TESTING", "false")
    monkeypatch.setenv("SECRET_KEY", "s" * 40)
    monkeypatch.setenv("JWT_SECRET_KEY", "j" * 40)


def test_warns_when_csrf_enforced_without_cookie_domain(monkeypatch, caplog) -> None:
    _secure_runtime_with_strong_secrets(monkeypatch)
    monkeypatch.setenv("AURAXIS_CSRF_ENFORCE", "true")
    monkeypatch.delenv("JWT_COOKIE_DOMAIN", raising=False)
    module = _reload_config_module()

    with caplog.at_level(logging.WARNING):
        module.validate_security_configuration()

    assert any("JWT_COOKIE_DOMAIN" in record.message for record in caplog.records)


def test_no_cookie_domain_warning_when_domain_is_set(monkeypatch, caplog) -> None:
    _secure_runtime_with_strong_secrets(monkeypatch)
    monkeypatch.setenv("AURAXIS_CSRF_ENFORCE", "true")
    monkeypatch.setenv("JWT_COOKIE_DOMAIN", ".auraxis.com.br")
    module = _reload_config_module()

    with caplog.at_level(logging.WARNING):
        module.validate_security_configuration()

    assert not any("JWT_COOKIE_DOMAIN" in record.message for record in caplog.records)


def test_no_cookie_domain_warning_when_csrf_disabled(monkeypatch, caplog) -> None:
    _secure_runtime_with_strong_secrets(monkeypatch)
    monkeypatch.setenv("AURAXIS_CSRF_ENFORCE", "false")
    monkeypatch.delenv("JWT_COOKIE_DOMAIN", raising=False)
    module = _reload_config_module()

    with caplog.at_level(logging.WARNING):
        module.validate_security_configuration()

    assert not any("JWT_COOKIE_DOMAIN" in record.message for record in caplog.records)
