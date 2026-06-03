from __future__ import annotations

import os
from dataclasses import dataclass

from flask import Flask, Response, request


@dataclass(frozen=True)
class CorsPolicy:
    allowed_origins: set[str]
    allow_credentials: bool
    allow_methods: str
    allow_headers: str
    max_age_seconds: int
    is_production: bool


def _parse_allowed_origins(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_cors_policy_from_env() -> CorsPolicy:
    is_debug = _read_bool_env("FLASK_DEBUG", False)
    is_testing = _read_bool_env("FLASK_TESTING", False)
    is_production = not (is_debug or is_testing)

    allowed_methods = os.getenv(
        "CORS_ALLOWED_METHODS",
        "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    ).strip()
    # X-CSRF-TOKEN is required for the SEC-AUD-03 double-submit refresh flow:
    # the browser preflights POST /auth/refresh with this header whenever
    # AURAXIS_CSRF_ENFORCE=true, so omitting it blocks session restore on every
    # hard reload (#1436).
    allowed_headers = os.getenv(
        "CORS_ALLOWED_HEADERS",
        "Authorization,Content-Type,X-API-Contract,Idempotency-Key,X-CSRF-TOKEN",
    ).strip()
    return CorsPolicy(
        allowed_origins=_parse_allowed_origins(os.getenv("CORS_ALLOWED_ORIGINS")),
        allow_credentials=_read_bool_env("CORS_ALLOW_CREDENTIALS", True),
        allow_methods=allowed_methods,
        allow_headers=allowed_headers,
        max_age_seconds=int(os.getenv("CORS_MAX_AGE_SECONDS", "600")),
        is_production=is_production,
    )


def _validate_cors_policy(policy: CorsPolicy) -> None:
    if policy.allow_credentials and "*" in policy.allowed_origins:
        raise RuntimeError(
            "CORS misconfiguration: wildcard origin is not allowed when "
            "CORS_ALLOW_CREDENTIALS=true."
        )

    if policy.is_production and not policy.allowed_origins:
        raise RuntimeError(
            "CORS misconfiguration: CORS_ALLOWED_ORIGINS must be configured "
            "for production environments."
        )

    if policy.is_production and "*" in policy.allowed_origins:
        raise RuntimeError(
            "CORS misconfiguration: wildcard origin is forbidden in production."
        )


def _is_allowed_origin(origin: str, allowed_origins: set[str]) -> bool:
    return "*" in allowed_origins or origin in allowed_origins


def register_cors(app: Flask) -> None:
    policy = _build_cors_policy_from_env()
    _validate_cors_policy(policy)
    app.extensions["cors_policy"] = policy

    @app.after_request
    def add_cors_headers(response: Response) -> Response:
        origin = request.headers.get("Origin")
        if not origin or not _is_allowed_origin(origin, policy.allowed_origins):
            return response

        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = (
            "true" if policy.allow_credentials else "false"
        )
        response.headers["Access-Control-Allow-Methods"] = policy.allow_methods
        response.headers["Access-Control-Allow-Headers"] = policy.allow_headers
        response.headers["Access-Control-Max-Age"] = str(policy.max_age_seconds)
        return response

    @app.before_request
    def handle_cors_preflight() -> Response | None:
        if request.method != "OPTIONS":
            return None

        origin = request.headers.get("Origin", "")
        if not _is_allowed_origin(origin, policy.allowed_origins):
            return None

        response = app.make_response(("", 204))
        return add_cors_headers(response)
