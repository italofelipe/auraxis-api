from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from flask import Flask, Response, current_app, g, jsonify, request
from flask_jwt_extended import decode_token

from app.extensions.integration_metrics import increment_metric
from app.middleware.rate_limit_settings import (
    RateLimitSettings,
    build_rate_limit_settings,
)
from app.middleware.rate_limit_storage import (
    RateLimitStorage,
    _build_storage_from_env,
)
from app.utils.api_contract import is_v2_contract_request
from app.utils.response_builder import error_payload

RATE_LIMIT_ERROR_CODE = "RATE_LIMIT_EXCEEDED"
RATE_LIMIT_MESSAGE = "Limite de requisições excedido. Tente novamente em instantes."
RATE_LIMIT_BACKEND_UNAVAILABLE_CODE = "RATE_LIMIT_BACKEND_UNAVAILABLE"
RATE_LIMIT_BACKEND_UNAVAILABLE_MESSAGE = (
    "Serviço temporariamente indisponível. Tente novamente em instantes."
)

KEY_SCOPE_IP = "ip"
KEY_SCOPE_USER_OR_IP = "user_or_ip"

_SKIPPED_ENDPOINTS = {
    "static",
    "swaggerui.index",
    "swaggerui.static",
    "swaggerui.swagger_json",
    "swagger-ui",
    "swagger-ui.static",
    "swagger-ui.swagger_json",
}


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_client_ip() -> str:
    trust_proxy_headers = _read_bool_env("RATE_LIMIT_TRUST_PROXY_HEADERS", False)
    if trust_proxy_headers:
        forwarded_for = str(request.headers.get("X-Forwarded-For", "")).strip()
        if forwarded_for:
            first_hop = forwarded_for.split(",")[0].strip()
            if first_hop:
                return first_hop
        real_ip = str(request.headers.get("X-Real-IP", "")).strip()
        if real_ip:
            return real_ip
    return str(request.remote_addr or "unknown")


def _extract_subject_from_bearer_token() -> str | None:
    auth_header = str(request.headers.get("Authorization", "")).strip()
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return None

    try:
        decoded = decode_token(token, allow_expired=False)
    except Exception:
        return None

    subject = decoded.get("sub")
    if subject is None:
        return None
    subject_str = str(subject).strip()
    return subject_str or None


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int
    key_scope: str


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    rule: RateLimitRule
    remaining: int
    retry_after_seconds: int
    key: str

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.rule.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.retry_after_seconds),
            "X-RateLimit-Rule": self.rule.name,
        }


class RateLimiterService:
    def __init__(
        self,
        *,
        rules: dict[str, RateLimitRule],
        storage: "RateLimitStorage",
        settings: RateLimitSettings,
        backend_name: str,
        configured_backend: str,
        backend_ready: bool,
        backend_failure_reason: str | None = None,
    ) -> None:
        self._rules = rules
        self._storage = storage
        self._enabled = settings.enabled
        self.backend_name = backend_name
        self.configured_backend = configured_backend
        self.backend_ready = backend_ready
        self.degraded_mode = settings.degraded_mode
        self.fail_closed = settings.fail_closed
        self.backend_failure_reason = backend_failure_reason
        self._route_rule_order: tuple[tuple[str, str], ...] = (
            # ── strict auth tier (IP-keyed) ──────────────────────────────
            ("/auth/refresh", "token_refresh"),
            ("/auth/login", "auth"),
            ("/auth/register", "auth"),
            ("/auth/password", "auth"),
            # ── billing checkout (IP-keyed) ──────────────────────────────
            # Each request holds one of the 4 gunicorn threads on a blocking
            # HTTP call to the PSP, so the lenient `default` tier (300/window)
            # made this a cheap way to starve the whole API. Capped at 10 —
            # a human subscribes once, and even an indecisive one does not
            # open ten checkouts a minute. Must stay above the webhook entry's
            # sibling prefix so neither shadows the other (#1632).
            ("/subscriptions/checkout", "checkout"),
            # ── billing webhook (IP-keyed) ───────────────────────────────
            # Provider callback — no JWT. Capped at 60/min per IP to absorb
            # legitimate retry bursts while blocking automated abuse.
            ("/subscriptions/webhook", "webhook"),
            # ── simulations save (user-keyed) ────────────────────────────
            # POST /simulations is the canonical generic save endpoint
            # (DEC-196 / #1128). Capped at 60 saves/min/user to block
            # scripted abuse while leaving room for legitimate batch UX.
            # Resolved by detecting POST on /simulations in
            # _resolve_effective_path before calling consume().
            ("/simulations/save", "simulations_save"),
            # ── GraphQL mutations — stricter limit than queries ───────────
            # Mutations are write operations; a lower ceiling prevents abuse
            # of create_* endpoints (goals, transactions, budgets, etc.).
            # The synthetic path "/graphql/mutation" is resolved by detecting
            # the "mutation" keyword in the request body before calling consume().
            ("/graphql/mutation", "graphql_mutation"),
            # ── GraphQL queries (user/IP-keyed) ──────────────────────────
            ("/graphql", "graphql"),
            # ── high-volume CRUD tiers (user/IP-keyed) ───────────────────
            ("/transactions", "transactions"),
            ("/wallet", "wallet"),
            # ── read-heavy endpoints: 120 req/window (user/IP-keyed) ─────
            # Explicit tier prevents accidental fall-through to the very
            # lenient `default` (300 req/window) rule.
            ("/dashboard", "read"),
            ("/goals", "read"),
            ("/alerts", "read"),
            ("/budget", "read"),
            ("/income", "read"),
            ("/portfolio", "read"),
            ("/shared-entries", "read"),
            ("/simulation", "read"),
            # ── settings-like endpoints: 60 req/window (user/IP-keyed) ───
            # Low-churn resources where bursts beyond 60 req/min indicate
            # scraping or abuse rather than normal usage.
            ("/account", "settings"),
            ("/credit-card", "settings"),
            ("/tag", "settings"),
            ("/user", "settings"),
            ("/investor-profile", "settings"),
        )

    @classmethod
    def from_env(cls) -> "RateLimiterService":
        default_window = _read_int_env("RATE_LIMIT_DEFAULT_WINDOW_SECONDS", 60)
        rules = {
            "auth": RateLimitRule(
                name="auth",
                limit=_read_int_env("RATE_LIMIT_AUTH_LIMIT", 20),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_AUTH_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_IP,
            ),
            "token_refresh": RateLimitRule(
                name="token_refresh",
                limit=_read_int_env("RATE_LIMIT_TOKEN_REFRESH_LIMIT", 10),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_TOKEN_REFRESH_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_IP,
            ),
            # Billing checkout: IP-keyed on purpose, even though the endpoint
            # requires a JWT. Keying by user would let one attacker rotate
            # accounts to keep every gunicorn thread parked on the PSP call;
            # keying by IP caps the whole origin. Safe because
            # RATE_LIMIT_TRUST_PROXY_HEADERS=true in prod and nginx forwards
            # X-Forwarded-For — without that, every request would share the
            # proxy's address and 10/window would be a global cap (#1632).
            "checkout": RateLimitRule(
                name="checkout",
                limit=_read_int_env("RATE_LIMIT_CHECKOUT_LIMIT", 10),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_CHECKOUT_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_IP,
            ),
            # Billing webhook: IP-keyed, generous for provider retry bursts.
            # Providers typically send at most a handful of retries per event.
            "webhook": RateLimitRule(
                name="webhook",
                limit=_read_int_env("RATE_LIMIT_WEBHOOK_LIMIT", 60),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_WEBHOOK_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_IP,
            ),
            "graphql_mutation": RateLimitRule(
                name="graphql_mutation",
                limit=_read_int_env("RATE_LIMIT_GRAPHQL_MUTATION_LIMIT", 30),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_GRAPHQL_MUTATION_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_USER_OR_IP,
            ),
            "graphql": RateLimitRule(
                name="graphql",
                limit=_read_int_env("RATE_LIMIT_GRAPHQL_LIMIT", 120),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_GRAPHQL_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_USER_OR_IP,
            ),
            "transactions": RateLimitRule(
                name="transactions",
                limit=_read_int_env("RATE_LIMIT_TRANSACTIONS_LIMIT", 180),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_TRANSACTIONS_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_USER_OR_IP,
            ),
            "wallet": RateLimitRule(
                name="wallet",
                limit=_read_int_env("RATE_LIMIT_WALLET_LIMIT", 180),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_WALLET_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_USER_OR_IP,
            ),
            # read-heavy endpoints: dashboard, goals, alerts, budget, etc.
            # 120 req/window — same cadence as GraphQL, user/IP-keyed.
            "read": RateLimitRule(
                name="read",
                limit=_read_int_env("RATE_LIMIT_READ_LIMIT", 120),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_READ_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_USER_OR_IP,
            ),
            # settings-like endpoints: account, credit-card, tag, user, etc.
            # 60 req/window — low-churn resources; bursts signal abuse.
            "settings": RateLimitRule(
                name="settings",
                limit=_read_int_env("RATE_LIMIT_SETTINGS_LIMIT", 60),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_SETTINGS_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_USER_OR_IP,
            ),
            # POST /simulations canonical save (DEC-196 / #1128).
            # 60 saves/min/user — capacity for legitimate batch UX,
            # ceiling for scripted abuse.
            "simulations_save": RateLimitRule(
                name="simulations_save",
                limit=_read_int_env("RATE_LIMIT_SIMULATIONS_SAVE_LIMIT", 60),
                window_seconds=_read_int_env(
                    "RATE_LIMIT_SIMULATIONS_SAVE_WINDOW_SECONDS", default_window
                ),
                key_scope=KEY_SCOPE_USER_OR_IP,
            ),
            "default": RateLimitRule(
                name="default",
                limit=_read_int_env("RATE_LIMIT_DEFAULT_LIMIT", 300),
                window_seconds=default_window,
                key_scope=KEY_SCOPE_USER_OR_IP,
            ),
        }
        (
            storage,
            backend_name,
            backend_ready,
            configured_backend,
            backend_failure_reason,
        ) = _build_storage_from_env()
        settings = build_rate_limit_settings(
            configured_backend=configured_backend,
        )
        return cls(
            rules=rules,
            storage=storage,
            settings=settings,
            backend_name=backend_name,
            configured_backend=configured_backend,
            backend_ready=backend_ready,
            backend_failure_reason=backend_failure_reason,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_rule(
        self,
        name: str,
        *,
        limit: int | None = None,
        window_seconds: int | None = None,
    ) -> None:
        current = self._rules.get(name)
        if current is None:
            raise KeyError(f"Rate limit rule '{name}' not found.")
        resolved_limit = current.limit if limit is None else max(limit, 1)
        resolved_window = (
            current.window_seconds if window_seconds is None else max(window_seconds, 1)
        )
        self._rules[name] = RateLimitRule(
            name=current.name,
            limit=resolved_limit,
            window_seconds=resolved_window,
            key_scope=current.key_scope,
        )
        self.reset()

    def reset(self) -> None:
        self._storage.reset()

    def _resolve_rule(self, path: str) -> RateLimitRule:
        for prefix, rule_name in self._route_rule_order:
            if path == prefix or path.startswith(f"{prefix}/"):
                return self._rules[rule_name]
        return self._rules["default"]

    @staticmethod
    def _resolve_rate_limit_key(
        *,
        rule: RateLimitRule,
        user_subject: str | None,
        client_ip: str,
    ) -> str:
        if rule.key_scope == KEY_SCOPE_IP:
            return f"ip:{client_ip}"
        if user_subject:
            return f"user:{user_subject}"
        return f"ip:{client_ip}"

    def consume(
        self,
        *,
        path: str,
        user_subject: str | None,
        client_ip: str,
    ) -> RateLimitDecision:
        rule = self._resolve_rule(path)
        key = self._resolve_rate_limit_key(
            rule=rule,
            user_subject=user_subject,
            client_ip=client_ip,
        )
        consumed, retry_after_seconds = self._storage.consume(
            rule_name=rule.name,
            key=key,
            window_seconds=rule.window_seconds,
        )
        allowed = consumed <= rule.limit
        remaining = max(rule.limit - min(consumed, rule.limit), 0)
        return RateLimitDecision(
            allowed=allowed,
            rule=rule,
            remaining=remaining,
            retry_after_seconds=max(1, retry_after_seconds),
            key=key,
        )


def _build_rate_limited_response(decision: RateLimitDecision) -> Response:
    increment_metric("rate_limit.blocked")
    increment_metric(f"rate_limit.blocked.{decision.rule.name}")
    details = {
        "rule": decision.rule.name,
        "limit": decision.rule.limit,
        "window_seconds": decision.rule.window_seconds,
        "retry_after_seconds": decision.retry_after_seconds,
    }
    if is_v2_contract_request():
        payload = error_payload(
            message=RATE_LIMIT_MESSAGE,
            code=RATE_LIMIT_ERROR_CODE,
            details=details,
        )
    else:
        payload = {
            "message": "Too many requests",
            "error": RATE_LIMIT_ERROR_CODE,
            "details": details,
        }

    response = jsonify(payload)
    response.status_code = 429
    for header_name, header_value in decision.headers().items():
        response.headers[header_name] = header_value
    response.headers["Retry-After"] = str(decision.retry_after_seconds)
    return response


def _build_backend_unavailable_response(reason: str | None = None) -> Response:
    increment_metric("rate_limit.backend_unavailable")
    details: dict[str, Any] = {}
    if reason:
        details["reason"] = reason

    if is_v2_contract_request():
        payload = error_payload(
            message=RATE_LIMIT_BACKEND_UNAVAILABLE_MESSAGE,
            code=RATE_LIMIT_BACKEND_UNAVAILABLE_CODE,
            details=details,
        )
    else:
        payload = {
            "message": RATE_LIMIT_BACKEND_UNAVAILABLE_MESSAGE,
            "error": RATE_LIMIT_BACKEND_UNAVAILABLE_CODE,
            "details": details,
        }

    response = jsonify(payload)
    response.status_code = 503
    response.headers["Retry-After"] = "5"
    return response


def _is_graphql_mutation_request() -> bool:
    """True when the current POST to /graphql is a write mutation operation."""
    if request.path != "/graphql" or request.method != "POST":
        return False
    payload = request.get_json(silent=True, force=True)
    if not isinstance(payload, dict):
        return False
    query = str(payload.get("query", "")).lstrip()
    return query.lower().startswith("mutation")


def _is_simulations_save_request() -> bool:
    """True when the current request is the canonical POST /simulations save.

    Other simulation endpoints (the legacy installment-vs-cash routes and the
    detail/delete routes under /simulations/<id>) keep their default rule.
    """
    return request.path == "/simulations" and request.method == "POST"


def _resolve_effective_path() -> str:
    """Map the current request path to a synthetic path used by rate-limit rules.

    Returns ``request.path`` for routes that already match a rule prefix; for
    request shapes that need bespoke routing (GraphQL mutations, the canonical
    simulations save) we return a synthetic path that the rule order resolves
    to a stricter rule.
    """
    if _is_graphql_mutation_request():
        return "/graphql/mutation"
    if _is_simulations_save_request():
        return "/simulations/save"
    return request.path


def _should_skip_rate_limit() -> bool:
    if request.method == "OPTIONS":
        return True
    if request.path.startswith("/docs"):
        return True
    if request.endpoint in _SKIPPED_ENDPOINTS:
        return True
    return False


def _is_fail_closed_active(limiter: RateLimiterService) -> bool:
    return (
        limiter.fail_closed
        and limiter.configured_backend == "redis"
        and not limiter.backend_ready
    )


def _consume_with_backend_guard(
    limiter: RateLimiterService,
    *,
    effective_path: str | None = None,
) -> RateLimitDecision | Response | None:
    if _is_fail_closed_active(limiter):
        if current_app:
            current_app.logger.warning(
                "rate_limit_backend_unavailable configured_backend=%s reason=%s",
                limiter.configured_backend,
                limiter.backend_failure_reason or "unknown",
            )
        return _build_backend_unavailable_response(limiter.backend_failure_reason)

    path = effective_path if effective_path is not None else request.path
    try:
        return limiter.consume(
            path=path,
            user_subject=_extract_subject_from_bearer_token(),
            client_ip=_get_client_ip(),
        )
    except Exception:
        increment_metric("rate_limit.backend_error")
        if current_app:
            current_app.logger.exception(
                "rate_limit_backend_error configured_backend=%s path=%s",
                limiter.configured_backend,
                path,
            )
        if limiter.fail_closed and limiter.configured_backend == "redis":
            return _build_backend_unavailable_response("rate limit backend error")
        return None


def _log_rate_limit_backend_configuration(
    app: Flask, limiter: RateLimiterService
) -> None:
    app.logger.info(
        (
            "rate_limit_backend_config configured_backend=%s "
            "backend_name=%s ready=%s degraded_mode=%s fail_closed=%s reason=%s"
        ),
        limiter.configured_backend,
        limiter.backend_name,
        limiter.backend_ready,
        limiter.degraded_mode,
        limiter.fail_closed,
        limiter.backend_failure_reason or "none",
    )
    if not _is_fail_closed_active(limiter):
        return
    app.logger.warning(
        "rate_limit_fail_closed_active configured_backend=%s reason=%s",
        limiter.configured_backend,
        limiter.backend_failure_reason or "unknown",
    )


def _record_allowed_decision_metrics(decision: RateLimitDecision) -> None:
    increment_metric("rate_limit.allowed")
    increment_metric(f"rate_limit.allowed.{decision.rule.name}")


def register_rate_limit_guard(app: Flask) -> None:
    limiter = RateLimiterService.from_env()
    if not limiter.enabled:
        return
    app.extensions["rate_limiter"] = limiter
    _log_rate_limit_backend_configuration(app, limiter)

    def rate_limit_guard() -> Response | None:
        if _should_skip_rate_limit():
            return None

        outcome = _consume_with_backend_guard(
            limiter, effective_path=_resolve_effective_path()
        )
        if isinstance(outcome, Response):
            return outcome
        if outcome is None:
            return None
        decision = outcome
        g.rate_limit_headers = decision.headers()
        _record_allowed_decision_metrics(decision)

        if decision.allowed:
            return None
        return _build_rate_limited_response(decision)

    def attach_rate_limit_headers(response: Response) -> Response:
        headers = getattr(g, "rate_limit_headers", None)
        if isinstance(headers, dict):
            for header_name, header_value in headers.items():
                response.headers[header_name] = str(header_value)
        return response

    app.before_request(rate_limit_guard)
    app.after_request(attach_rate_limit_headers)
