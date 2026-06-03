from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from flask import Flask, jsonify

from app import create_app
from app.middleware.cors import (
    CorsPolicy,
    _build_cors_policy_from_env,
    _is_allowed_origin,
    _parse_allowed_origins,
    _read_bool_env,
    _validate_cors_policy,
    register_cors,
)


def _build_app() -> Flask:
    app = Flask(__name__)

    @app.route("/ping", methods=["GET", "OPTIONS"])
    def ping() -> Any:
        return jsonify({"ok": True})

    return app


def test_parse_allowed_origins_handles_empty_and_whitespace() -> None:
    assert _parse_allowed_origins(None) == set()
    assert _parse_allowed_origins("") == set()
    assert _parse_allowed_origins(" ,  , ") == set()
    assert _parse_allowed_origins("https://a.com, https://b.com ") == {
        "https://a.com",
        "https://b.com",
    }


def test_read_bool_env_uses_default_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AURAXIS_FLAG", raising=False)
    assert _read_bool_env("AURAXIS_FLAG", True) is True
    assert _read_bool_env("AURAXIS_FLAG", False) is False


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_read_bool_env_true_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("AURAXIS_FLAG", raw)
    assert _read_bool_env("AURAXIS_FLAG", False) is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "anything-else"])
def test_read_bool_env_false_values(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("AURAXIS_FLAG", raw)
    assert _read_bool_env("AURAXIS_FLAG", True) is False


def test_build_cors_policy_from_env_respects_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.delenv("FLASK_TESTING", raising=False)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://api.auraxis.com.br")
    monkeypatch.delenv("CORS_ALLOW_CREDENTIALS", raising=False)
    monkeypatch.delenv("CORS_ALLOWED_METHODS", raising=False)
    monkeypatch.delenv("CORS_ALLOWED_HEADERS", raising=False)
    monkeypatch.delenv("CORS_MAX_AGE_SECONDS", raising=False)

    policy = _build_cors_policy_from_env()

    assert policy.allowed_origins == {"https://api.auraxis.com.br"}
    assert policy.allow_credentials is True
    assert policy.allow_methods == "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    assert policy.allow_headers == (
        "Authorization,Content-Type,X-API-Contract,Idempotency-Key,X-CSRF-TOKEN"
    )
    assert policy.max_age_seconds == 600
    assert policy.is_production is True


def test_default_allowed_headers_include_csrf_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """X-CSRF-TOKEN must be in the default CORS allow-list.

    The session-restore flow (SEC-GAP-01) re-mints the access token via
    POST /auth/refresh, sending the double-submit X-CSRF-TOKEN header
    (SEC-AUD-03) whenever AURAXIS_CSRF_ENFORCE=true. If the header is absent
    from Access-Control-Allow-Headers the browser preflight blocks the refresh
    on every hard reload, logging the user out. Regression guard for #1436.
    """
    monkeypatch.delenv("CORS_ALLOWED_HEADERS", raising=False)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.auraxis.com.br")

    policy = _build_cors_policy_from_env()

    assert "X-CSRF-TOKEN" in policy.allow_headers.split(",")


def test_build_cors_policy_marks_non_production_when_testing_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLASK_DEBUG", "false")
    monkeypatch.setenv("FLASK_TESTING", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "")
    policy = _build_cors_policy_from_env()
    assert policy.is_production is False


def test_validate_cors_policy_blocks_wildcard_with_credentials() -> None:
    policy = CorsPolicy(
        allowed_origins={"*"},
        allow_credentials=True,
        allow_methods="GET",
        allow_headers="Authorization",
        max_age_seconds=600,
        is_production=False,
    )
    with pytest.raises(RuntimeError):
        _validate_cors_policy(policy)


def test_validate_cors_policy_allows_production_with_explicit_origin() -> None:
    policy = CorsPolicy(
        allowed_origins={"https://frontend.auraxis.com.br"},
        allow_credentials=False,
        allow_methods="GET",
        allow_headers="Authorization",
        max_age_seconds=600,
        is_production=True,
    )
    _validate_cors_policy(policy)


def test_validate_cors_policy_requires_origins_in_production() -> None:
    policy = CorsPolicy(
        allowed_origins=set(),
        allow_credentials=False,
        allow_methods="GET",
        allow_headers="Authorization",
        max_age_seconds=600,
        is_production=True,
    )
    with pytest.raises(RuntimeError):
        _validate_cors_policy(policy)


def test_validate_cors_policy_blocks_wildcard_in_production() -> None:
    policy = CorsPolicy(
        allowed_origins={"*"},
        allow_credentials=False,
        allow_methods="GET",
        allow_headers="Authorization",
        max_age_seconds=600,
        is_production=True,
    )
    with pytest.raises(RuntimeError):
        _validate_cors_policy(policy)


def test_validate_cors_policy_allows_non_prod_wildcard_without_credentials() -> None:
    policy = CorsPolicy(
        allowed_origins={"*"},
        allow_credentials=False,
        allow_methods="GET",
        allow_headers="Authorization",
        max_age_seconds=600,
        is_production=False,
    )
    _validate_cors_policy(policy)


def test_cors_policy_is_immutable() -> None:
    policy = CorsPolicy(
        allowed_origins={"https://frontend.auraxis.com.br"},
        allow_credentials=True,
        allow_methods="GET,POST",
        allow_headers="Authorization",
        max_age_seconds=600,
        is_production=False,
    )

    with pytest.raises(FrozenInstanceError):
        policy.allow_methods = "GET"  # type: ignore[misc]


def test_is_allowed_origin_accepts_exact_and_wildcard() -> None:
    assert _is_allowed_origin("https://allowed.com", {"https://allowed.com"}) is True
    assert _is_allowed_origin("https://any.com", {"*"}) is True
    assert _is_allowed_origin("https://denied.com", {"https://allowed.com"}) is False


def test_register_cors_applies_headers_for_allowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://frontend.auraxis.com.br")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")
    monkeypatch.setenv("CORS_ALLOWED_METHODS", "GET,POST,OPTIONS")
    monkeypatch.setenv("CORS_ALLOWED_HEADERS", "Authorization,Content-Type")
    monkeypatch.setenv("CORS_MAX_AGE_SECONDS", "1200")

    app = _build_app()
    register_cors(app)
    client = app.test_client()

    response = client.get(
        "/ping",
        headers={"Origin": "https://frontend.auraxis.com.br"},
    )

    assert response.status_code == 200
    assert (
        response.headers.get("Access-Control-Allow-Origin")
        == "https://frontend.auraxis.com.br"
    )
    assert response.headers.get("Access-Control-Allow-Credentials") == "true"
    assert response.headers.get("Access-Control-Allow-Methods") == "GET,POST,OPTIONS"
    assert response.headers.get("Access-Control-Allow-Headers") == (
        "Authorization,Content-Type"
    )
    assert response.headers.get("Access-Control-Max-Age") == "1200"
    assert response.headers.get("Vary") == "Origin"


def test_register_cors_skips_headers_for_disallowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://frontend.auraxis.com.br")

    app = _build_app()
    register_cors(app)
    client = app.test_client()

    response = client.get("/ping", headers={"Origin": "https://malicious.example"})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_register_cors_handles_preflight_for_allowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://frontend.auraxis.com.br")

    app = _build_app()
    register_cors(app)
    client = app.test_client()

    response = client.options(
        "/ping",
        headers={"Origin": "https://frontend.auraxis.com.br"},
    )
    assert response.status_code == 204
    assert (
        response.headers.get("Access-Control-Allow-Origin")
        == "https://frontend.auraxis.com.br"
    )


def test_register_cors_preflight_echoes_default_csrf_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end guard for #1436: with default headers, the OPTIONS preflight
    for an allowed origin must advertise X-CSRF-TOKEN so the browser permits the
    credentialed POST /auth/refresh that restores the session on reload."""
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "true")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.auraxis.com.br")
    monkeypatch.delenv("CORS_ALLOWED_HEADERS", raising=False)

    app = _build_app()
    register_cors(app)
    client = app.test_client()

    response = client.options(
        "/ping",
        headers={"Origin": "https://app.auraxis.com.br"},
    )

    assert response.status_code == 204
    allow_headers = response.headers.get("Access-Control-Allow-Headers", "")
    assert "X-CSRF-TOKEN" in allow_headers.split(",")


def test_register_cors_rejects_invalid_production_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLASK_DEBUG", "false")
    monkeypatch.setenv("FLASK_TESTING", "false")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    app = _build_app()
    with pytest.raises(RuntimeError):
        register_cors(app)


def test_create_app_allows_internal_runtime_without_cors_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLASK_DEBUG", "false")
    monkeypatch.setenv("FLASK_TESTING", "false")
    monkeypatch.setenv("AURAXIS_ENV", "production")
    monkeypatch.setenv("SECURITY_ENFORCE_STRONG_SECRETS", "true")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv(
        "SECRET_KEY",
        "prod-secret-key-with-64-chars-minimum-for-runtime-check-0001",
    )
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "prod-jwt-secret-key-with-64-chars-minimum-for-runtime-check-0002",
    )
    internal_db_path = tmp_path / "internal-runtime.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{internal_db_path}")

    app = create_app(enable_http_runtime=False)

    assert "cors_policy" not in app.extensions


def test_create_app_still_requires_cors_policy_for_http_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FLASK_DEBUG", "false")
    monkeypatch.setenv("FLASK_TESTING", "false")
    monkeypatch.setenv("AURAXIS_ENV", "production")
    monkeypatch.setenv("SECURITY_ENFORCE_STRONG_SECRETS", "true")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv(
        "SECRET_KEY",
        "prod-secret-key-with-64-chars-minimum-for-runtime-check-0001",
    )
    monkeypatch.setenv(
        "JWT_SECRET_KEY",
        "prod-jwt-secret-key-with-64-chars-minimum-for-runtime-check-0002",
    )
    http_db_path = tmp_path / "http-runtime.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{http_db_path}")

    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        create_app()


# ---------------------------------------------------------------------------
# Production domain coverage tests
# ---------------------------------------------------------------------------

_PRODUCTION_ORIGINS = [
    "https://app.auraxis.com.br",
    "https://pilot.auraxis.com.br",
    "https://www.auraxis.com.br",
]


@pytest.mark.parametrize("origin", _PRODUCTION_ORIGINS)
def test_production_origins_are_allowed(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    """Each canonical production origin must be accepted by the CORS policy."""
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "true")
    allowed = ",".join(_PRODUCTION_ORIGINS)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", allowed)

    assert _is_allowed_origin(origin, set(_PRODUCTION_ORIGINS)) is True


@pytest.mark.parametrize("origin", _PRODUCTION_ORIGINS)
def test_register_cors_allows_preflight_for_production_origins(
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    """OPTIONS preflight must echo Access-Control-Allow-Origin for each origin."""
    monkeypatch.setenv("FLASK_DEBUG", "true")
    monkeypatch.setenv("FLASK_TESTING", "true")
    allowed = ",".join(_PRODUCTION_ORIGINS)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", allowed)

    app = _build_app()
    register_cors(app)
    client = app.test_client()

    response = client.options(
        "/ping",
        headers={"Origin": origin},
    )
    assert response.status_code == 204
    assert response.headers.get("Access-Control-Allow-Origin") == origin


def test_parse_allowed_origins_includes_pilot_domain() -> None:
    """pilot.auraxis.com.br must be parseable as a valid CORS origin."""
    origins = _parse_allowed_origins(
        "https://app.auraxis.com.br,https://pilot.auraxis.com.br,https://www.auraxis.com.br"
    )
    assert "https://pilot.auraxis.com.br" in origins
    assert "https://app.auraxis.com.br" in origins
    assert "https://www.auraxis.com.br" in origins
