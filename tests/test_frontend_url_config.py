"""Every ``*_FRONTEND_URL`` the app emails out must reach the Flask config.

The services that build these links read them with ``runtime_config``, which
looks at ``current_app.config`` — not at ``os.getenv``. A variable that exists
in the container but is never declared in ``config/__init__.py`` therefore
resolves to its default, and the email goes out with a dead link.

That is exactly what happened to password reset (#1650): the env was correct in
``.env.prod`` *and* in the running container, but the config never read it, so
every recovery email shipped ``reset_url = "n/a"``. Confirmação de e-mail was
fine only because its key happened to be declared.

These tests pin the env → config → link chain for both keys.
"""

from __future__ import annotations

import importlib

import pytest

# Keys consumed via `runtime_config` by the email-sending services. Add a key
# here when a new service starts emailing a frontend link.
FRONTEND_URL_KEYS = (
    "PASSWORD_RESET_FRONTEND_URL",
    "EMAIL_CONFIRMATION_FRONTEND_URL",
)


@pytest.mark.parametrize("key", FRONTEND_URL_KEYS)
def test_key_is_declared_in_config(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The config must expose the key — otherwise runtime_config sees nothing."""
    expected = f"https://app.auraxis.com.br/rota-de-{key.lower()}"
    monkeypatch.setenv(key, expected)

    import config

    importlib.reload(config)
    assert getattr(config.Config, key, None) == expected, (
        f"{key} is set in the environment but does not reach Flask config — "
        "the service reading it via runtime_config will fall back to its default"
    )


@pytest.mark.parametrize("key", FRONTEND_URL_KEYS)
def test_key_defaults_to_empty_string_when_unset(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(key, raising=False)

    import config

    importlib.reload(config)
    assert getattr(config.Config, key, None) == ""


def test_password_reset_email_carries_a_real_url(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End of the chain: a configured env produces a clickable link.

    Regression for the report where the button and the copy-paste fallback both
    read "n/a".
    """
    from app.application.services.password_reset_service import (
        _dispatch_reset_instructions,
    )

    base = "https://app.auraxis.com.br/reset-password"
    with app.app_context():
        app.config["PASSWORD_RESET_FRONTEND_URL"] = base
        app.extensions.pop("password_reset_outbox", None)
        _dispatch_reset_instructions(email="user@test.com", token="tok-123")
        sent = app.extensions["password_reset_outbox"]

    assert sent, "nothing was dispatched"
    reset_url = sent[-1]["reset_url"]
    assert reset_url != "n/a"
    assert reset_url == f"{base}?token=tok-123"


def test_password_reset_email_falls_back_only_when_unconfigured(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "n/a" stays reachable — but only for a genuinely missing config."""
    from app.application.services.password_reset_service import (
        _dispatch_reset_instructions,
    )

    with app.app_context():
        app.config["PASSWORD_RESET_FRONTEND_URL"] = ""
        app.extensions.pop("password_reset_outbox", None)
        _dispatch_reset_instructions(email="user@test.com", token="tok-123")
        sent = app.extensions["password_reset_outbox"]

    assert sent[-1]["reset_url"] == "n/a"
