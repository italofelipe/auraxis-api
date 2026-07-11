"""Canonical Prometheus metrics for auraxis-api (API23).

Exposes three core instrument families via ``prometheus_client``:

- ``auraxis_http_requests_total``           — Counter {method, endpoint, status_code}
- ``auraxis_http_request_duration_seconds`` — Histogram {method, endpoint}
- ``auraxis_auth_logins_total``             — Counter {status}

All metrics are process-level singletons.  They are safe under gunicorn
multi-worker fork mode because each worker gets its own copy after forking.
For spawn-mode multiprocess, set ``PROMETHEUS_MULTIPROC_DIR`` — the
prometheus_client library will aggregate across workers automatically.

Usage
-----
Call ``register_prometheus_middleware(app)`` once in ``create_app()`` to wire
the request instrumentation hooks.  The ``/ops/metrics`` endpoint is handled
by the observability controller which calls ``generate_latest_metrics()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from flask import Flask

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    _PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PROMETHEUS_AVAILABLE = False

_HTTP_REQUESTS_TOTAL: Any = None
_HTTP_REQUEST_DURATION: Any = None
_AUTH_LOGINS_TOTAL: Any = None
_AUTH_LOGIN_COOKIE_ONLY_HEADER_TOTAL: Any = None
_AUDIT_EVENTS_PURGED_TOTAL: Any = None
_CACHE_HITS_TOTAL: Any = None
_CACHE_MISSES_TOTAL: Any = None
_CACHE_INVALIDATIONS_TOTAL: Any = None
_AI_INSIGHT_GENERATED_TOTAL: Any = None
_AI_INSIGHT_TOKENS: Any = None
_AI_INSIGHT_SNAPSHOT_BYTES: Any = None
_AI_INSIGHT_RUNS_TOTAL: Any = None
_AI_INSIGHT_COST_USD_TOTAL: Any = None
_AI_INSIGHT_REJECTIONS_TOTAL: Any = None
_AI_INSIGHT_TRUNCATED_TOTAL: Any = None
_AI_INSIGHT_DEPTH_BELOW_TARGET_TOTAL: Any = None
_AI_INSIGHT_DATA_QUALITY_DOMAINS: Any = None
_AI_INSIGHT_RUNS_PURGED_TOTAL: Any = None
_AI_CHAT_MESSAGES_TOTAL: Any = None

_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)
_AI_TOKENS_BUCKETS = (100, 250, 500, 1000, 2500, 5000, 10000, 25000)
_AI_SNAPSHOT_BYTES_BUCKETS = (1024, 2048, 4096, 8192, 12288, 16384, 32768)
_AI_DATA_QUALITY_DOMAIN_BUCKETS = (0, 1, 2, 3, 4, 5, 6)


def _init_ai_insight_metrics() -> None:  # noqa: C901 — flat list of counter inits
    """Lazily initialise the MVP-3 AI insight observability instruments."""
    global \
        _AI_INSIGHT_GENERATED_TOTAL, \
        _AI_CHAT_MESSAGES_TOTAL, \
        _AI_INSIGHT_TOKENS, \
        _AI_INSIGHT_SNAPSHOT_BYTES, \
        _AI_INSIGHT_RUNS_TOTAL, \
        _AI_INSIGHT_COST_USD_TOTAL, \
        _AI_INSIGHT_REJECTIONS_TOTAL, \
        _AI_INSIGHT_TRUNCATED_TOTAL, \
        _AI_INSIGHT_DEPTH_BELOW_TARGET_TOTAL, \
        _AI_INSIGHT_DATA_QUALITY_DOMAINS, \
        _AI_INSIGHT_RUNS_PURGED_TOTAL

    if _AI_INSIGHT_GENERATED_TOTAL is None:
        _AI_INSIGHT_GENERATED_TOTAL = Counter(
            "auraxis_ai_insight_generated_total",
            "AI insights generated, by period_type and dimension",
            ["period_type", "dimension"],
        )
    if _AI_CHAT_MESSAGES_TOTAL is None:
        _AI_CHAT_MESSAGES_TOTAL = Counter(
            "auraxis_ai_chat_messages_total",
            "Ask-anything chat answers, by tool usage and no-info outcome",
            ["tools_used", "no_info"],
        )
    if _AI_INSIGHT_TOKENS is None:
        _AI_INSIGHT_TOKENS = Histogram(
            "auraxis_ai_insight_tokens",
            "Tokens consumed per AI insight generation",
            ["period_type"],
            buckets=_AI_TOKENS_BUCKETS,
        )
    if _AI_INSIGHT_SNAPSHOT_BYTES is None:
        _AI_INSIGHT_SNAPSHOT_BYTES = Histogram(
            "auraxis_ai_insight_snapshot_bytes",
            "Snapshot size in bytes sent to the LLM (post truncation)",
            ["period_type", "truncated"],
            buckets=_AI_SNAPSHOT_BYTES_BUCKETS,
        )
    # #1314 — governance/quality observability for AI insight runs.
    if _AI_INSIGHT_RUNS_TOTAL is None:
        _AI_INSIGHT_RUNS_TOTAL = Counter(
            "auraxis_ai_insight_runs_total",
            (
                "AIInsightRun lifecycle state entries by status and period_type. "
                "A single logical run contributes once per status it enters "
                "(e.g. previewed then generated), so rates like "
                "rejected/previewed are derivable."
            ),
            ["status", "period_type"],
        )
    if _AI_INSIGHT_COST_USD_TOTAL is None:
        _AI_INSIGHT_COST_USD_TOTAL = Counter(
            "auraxis_ai_insight_cost_usd_total",
            "Cumulative estimated LLM cost (USD) attributed to AI insight runs",
            ["period_type"],
        )
    if _AI_INSIGHT_REJECTIONS_TOTAL is None:
        _AI_INSIGHT_REJECTIONS_TOTAL = Counter(
            "auraxis_ai_insight_rejections_total",
            "AI insight items rejected by the evidence validator, by reason",
            ["reason"],
        )
    if _AI_INSIGHT_TRUNCATED_TOTAL is None:
        _AI_INSIGHT_TRUNCATED_TOTAL = Counter(
            "auraxis_ai_insight_truncated_total",
            "AI insight runs whose snapshot was truncated before the LLM call",
            ["period_type"],
        )
    if _AI_INSIGHT_DEPTH_BELOW_TARGET_TOTAL is None:
        _AI_INSIGHT_DEPTH_BELOW_TARGET_TOTAL = Counter(
            "auraxis_ai_insight_depth_below_target_total",
            "AI insight generations whose text fell below the reading-time target",
            ["period_type"],
        )
    if _AI_INSIGHT_DATA_QUALITY_DOMAINS is None:
        _AI_INSIGHT_DATA_QUALITY_DOMAINS = Histogram(
            "auraxis_ai_insight_data_quality_domains",
            "Number of financial domains present in the run snapshot (0-6)",
            ["period_type"],
            buckets=_AI_DATA_QUALITY_DOMAIN_BUCKETS,
        )
    if _AI_INSIGHT_RUNS_PURGED_TOTAL is None:
        _AI_INSIGHT_RUNS_PURGED_TOTAL = Counter(
            "auraxis_ai_insight_runs_purged_total",
            "AIInsightRun snapshot payloads purged by the retention job",
        )


def _ensure_metrics_initialized() -> None:
    """Lazily initialise Prometheus metric objects (idempotent)."""
    global \
        _HTTP_REQUESTS_TOTAL, \
        _HTTP_REQUEST_DURATION, \
        _AUTH_LOGINS_TOTAL, \
        _AUTH_LOGIN_COOKIE_ONLY_HEADER_TOTAL, \
        _AUDIT_EVENTS_PURGED_TOTAL, \
        _CACHE_HITS_TOTAL, \
        _CACHE_MISSES_TOTAL, \
        _CACHE_INVALIDATIONS_TOTAL

    if not _PROMETHEUS_AVAILABLE:
        return

    if _HTTP_REQUESTS_TOTAL is None:
        _HTTP_REQUESTS_TOTAL = Counter(
            "auraxis_http_requests_total",
            "Total HTTP requests handled by auraxis-api",
            ["method", "endpoint", "status_code"],
        )

    if _HTTP_REQUEST_DURATION is None:
        _HTTP_REQUEST_DURATION = Histogram(
            "auraxis_http_request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
            buckets=_DURATION_BUCKETS,
        )

    if _AUTH_LOGINS_TOTAL is None:
        _AUTH_LOGINS_TOTAL = Counter(
            "auraxis_auth_logins_total",
            "Total login attempts (status: success | failure | mfa_required)",
            ["status"],
        )

    # SEC-AUD-07 / #623 — canary metric for the cookie-only refresh flip.
    # Labels:
    #   header_present: "yes" | "no" — whether the client sent
    #     X-Refresh-Cookie-Only on the login request.
    # When the global flag AURAXIS_REFRESH_COOKIE_ONLY is flipped to True,
    # responses stop carrying refresh_token in the body. Before flipping we
    # need 2 weeks of header_present="no" near zero to confirm every
    # production client has migrated.
    if _AUTH_LOGIN_COOKIE_ONLY_HEADER_TOTAL is None:
        _AUTH_LOGIN_COOKIE_ONLY_HEADER_TOTAL = Counter(
            "auraxis_auth_login_cookie_only_header_total",
            (
                "Successful logins by presence of X-Refresh-Cookie-Only "
                "header (canary for SEC-AUD-07)"
            ),
            ["header_present"],
        )

    if _AUDIT_EVENTS_PURGED_TOTAL is None:
        _AUDIT_EVENTS_PURGED_TOTAL = Counter(
            "auraxis_audit_events_purged_total",
            "Total audit_events rows deleted by the retention job",
        )

    if _CACHE_HITS_TOTAL is None:
        _CACHE_HITS_TOTAL = Counter(
            "auraxis_cache_hits_total",
            "Cache hits by key namespace",
            ["namespace"],
        )

    if _CACHE_MISSES_TOTAL is None:
        _CACHE_MISSES_TOTAL = Counter(
            "auraxis_cache_misses_total",
            "Cache misses by key namespace",
            ["namespace"],
        )

    if _CACHE_INVALIDATIONS_TOTAL is None:
        _CACHE_INVALIDATIONS_TOTAL = Counter(
            "auraxis_cache_invalidations_total",
            "Cache key invalidations by namespace",
            ["namespace"],
        )

    _init_ai_insight_metrics()


def record_http_request(
    *,
    method: str,
    endpoint: str,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Increment request counter and observe duration histogram."""
    _ensure_metrics_initialized()
    if _HTTP_REQUESTS_TOTAL is not None:
        _HTTP_REQUESTS_TOTAL.labels(
            method=method,
            endpoint=endpoint,
            status_code=str(status_code),
        ).inc()
    if _HTTP_REQUEST_DURATION is not None:
        _HTTP_REQUEST_DURATION.labels(
            method=method,
            endpoint=endpoint,
        ).observe(duration_seconds)


def record_audit_purge(count: int) -> None:
    """Increment ``auraxis_audit_events_purged_total`` by *count* rows deleted."""
    _ensure_metrics_initialized()
    if _AUDIT_EVENTS_PURGED_TOTAL is not None:
        _AUDIT_EVENTS_PURGED_TOTAL.inc(count)


def record_cache_hit(namespace: str) -> None:
    """Increment ``auraxis_cache_hits_total`` for the given namespace."""
    _ensure_metrics_initialized()
    if _CACHE_HITS_TOTAL is not None:
        _CACHE_HITS_TOTAL.labels(namespace=namespace).inc()


def record_cache_miss(namespace: str) -> None:
    """Increment ``auraxis_cache_misses_total`` for the given namespace."""
    _ensure_metrics_initialized()
    if _CACHE_MISSES_TOTAL is not None:
        _CACHE_MISSES_TOTAL.labels(namespace=namespace).inc()


def record_cache_invalidation(namespace: str) -> None:
    """Increment ``auraxis_cache_invalidations_total`` for the given namespace."""
    _ensure_metrics_initialized()
    if _CACHE_INVALIDATIONS_TOTAL is not None:
        _CACHE_INVALIDATIONS_TOTAL.labels(namespace=namespace).inc()


def record_auth_login(*, status: str) -> None:
    """Increment ``auraxis_auth_logins_total`` with the given status label.

    Canonical status values: ``success``, ``failure``, ``mfa_required``.
    """
    _ensure_metrics_initialized()
    if _AUTH_LOGINS_TOTAL is not None:
        _AUTH_LOGINS_TOTAL.labels(status=status).inc()


def record_auth_login_cookie_only_header(*, header_present: bool) -> None:
    """Canary for SEC-AUD-07 / #623.

    Increment ``auraxis_auth_login_cookie_only_header_total`` to track
    whether successful logins are arriving with the ``X-Refresh-Cookie-Only``
    header set. Call this **only on successful logins** so the denominator
    reflects real client traffic, not failed attempts.

    When the rate of ``header_present="no"`` is effectively zero for 2
    weeks in production, the global ``AURAXIS_REFRESH_COOKIE_ONLY`` flag
    can be flipped safely.
    """
    _ensure_metrics_initialized()
    if _AUTH_LOGIN_COOKIE_ONLY_HEADER_TOTAL is not None:
        label = "yes" if header_present else "no"
        _AUTH_LOGIN_COOKIE_ONLY_HEADER_TOTAL.labels(header_present=label).inc()


def record_ai_chat_answered(*, tool_rounds: int, no_info: bool) -> None:
    """Telemetry for the Ask-anything chat (#1548).

    ``no_info`` tracks answers admitting missing data — the trigger metric for
    deepening the tool set.
    """
    _ensure_metrics_initialized()
    if _AI_CHAT_MESSAGES_TOTAL is not None:
        _AI_CHAT_MESSAGES_TOTAL.labels(
            tools_used="true" if tool_rounds > 0 else "false",
            no_info="true" if no_info else "false",
        ).inc()


def record_ai_insight_generated(
    *,
    period_type: str,
    dimensions: list[str],
    tokens_used: int,
    snapshot_bytes: int,
    truncated: bool,
) -> None:
    """Record an AI insight generation across counter + histograms (MVP-3).

    Emits one ``auraxis_ai_insight_generated_total`` increment per distinct
    dimension found in the LLM response (so a single generation contributes
    to multiple dimensions when the LLM produces multi-surface items).
    Tokens and snapshot byte size are observed once per call.
    """
    _ensure_metrics_initialized()
    pt = period_type or "unknown"
    if _AI_INSIGHT_GENERATED_TOTAL is not None:
        for dim in dimensions or ["general"]:
            _AI_INSIGHT_GENERATED_TOTAL.labels(period_type=pt, dimension=dim).inc()
    if _AI_INSIGHT_TOKENS is not None and tokens_used >= 0:
        _AI_INSIGHT_TOKENS.labels(period_type=pt).observe(tokens_used)
    if _AI_INSIGHT_SNAPSHOT_BYTES is not None and snapshot_bytes >= 0:
        _AI_INSIGHT_SNAPSHOT_BYTES.labels(
            period_type=pt,
            truncated="true" if truncated else "false",
        ).observe(snapshot_bytes)


def record_ai_insight_run(*, status: str, period_type: str) -> None:
    """Count an ``AIInsightRun`` entering *status* (#1314).

    ``status`` is an ``AIInsightRunStatus`` value (previewed/generated/cached/
    rejected/blocked/failed/purged); ``period_type`` is an ``InsightType``
    value. Both are bounded enums — safe label cardinality, no PII.
    """
    _ensure_metrics_initialized()
    if _AI_INSIGHT_RUNS_TOTAL is not None:
        _AI_INSIGHT_RUNS_TOTAL.labels(
            status=status or "unknown",
            period_type=period_type or "unknown",
        ).inc()


def record_ai_insight_cost(*, period_type: str, cost_usd: float) -> None:
    """Add *cost_usd* to the cumulative AI insight cost counter (#1314)."""
    _ensure_metrics_initialized()
    if _AI_INSIGHT_COST_USD_TOTAL is not None and cost_usd > 0:
        _AI_INSIGHT_COST_USD_TOTAL.labels(
            period_type=period_type or "unknown",
        ).inc(cost_usd)


def record_ai_insight_rejection(*, reason: str) -> None:
    """Count one evidence-validation rejection by stable *reason* (#1314)."""
    _ensure_metrics_initialized()
    if _AI_INSIGHT_REJECTIONS_TOTAL is not None:
        _AI_INSIGHT_REJECTIONS_TOTAL.labels(reason=reason or "unknown").inc()


def record_ai_insight_truncated(*, period_type: str) -> None:
    """Count one AI insight run whose snapshot was truncated (#1314)."""
    _ensure_metrics_initialized()
    if _AI_INSIGHT_TRUNCATED_TOTAL is not None:
        _AI_INSIGHT_TRUNCATED_TOTAL.labels(
            period_type=period_type or "unknown",
        ).inc()


def record_ai_insight_depth_below_target(*, period_type: str) -> None:
    """Count one AI insight whose text fell short of the reading-time target.

    The depth gate is *advisory* (#1481): it never re-calls the LLM (that would
    double the cost) — it only surfaces shallow generations for monitoring so we
    can tune prompts/`max_tokens` over time.
    """
    _ensure_metrics_initialized()
    if _AI_INSIGHT_DEPTH_BELOW_TARGET_TOTAL is not None:
        _AI_INSIGHT_DEPTH_BELOW_TARGET_TOTAL.labels(
            period_type=period_type or "unknown",
        ).inc()


def record_ai_insight_data_quality(*, period_type: str, domains_present: int) -> None:
    """Observe how many financial domains were present in the run snapshot."""
    _ensure_metrics_initialized()
    if _AI_INSIGHT_DATA_QUALITY_DOMAINS is not None and domains_present >= 0:
        _AI_INSIGHT_DATA_QUALITY_DOMAINS.labels(
            period_type=period_type or "unknown",
        ).observe(domains_present)


def record_ai_insight_runs_purged(count: int) -> None:
    """Increment ``auraxis_ai_insight_runs_purged_total`` by *count* (#1314)."""
    _ensure_metrics_initialized()
    if _AI_INSIGHT_RUNS_PURGED_TOTAL is not None and count > 0:
        _AI_INSIGHT_RUNS_PURGED_TOTAL.inc(count)


def generate_latest_metrics() -> tuple[bytes, str]:
    """Return ``(body_bytes, content_type)`` for the Prometheus scrape endpoint.

    Falls back to an empty payload when ``prometheus_client`` is not installed.
    """
    _ensure_metrics_initialized()
    if not _PROMETHEUS_AVAILABLE:
        return b"", "text/plain; version=0.0.4; charset=utf-8"  # pragma: no cover
    body: bytes = generate_latest()
    content_type: str = CONTENT_TYPE_LATEST
    return body, content_type


def register_prometheus_middleware(app: "Flask") -> None:
    """Wire before/after_request hooks to populate Prometheus metrics."""
    from time import perf_counter

    from flask import Response, g

    _ensure_metrics_initialized()

    @app.before_request
    def _prom_mark_start() -> None:
        g.prom_request_started_at = perf_counter()

    @app.after_request
    def _prom_record_request(response: Response) -> Response:
        from app.http.request_context import get_request_context

        started_at: float | None = getattr(g, "prom_request_started_at", None)
        duration = (
            max(perf_counter() - started_at, 0.0)
            if isinstance(started_at, float)
            else 0.0
        )
        ctx = get_request_context(optional=True)
        method = ctx.method if ctx else "UNKNOWN"
        endpoint = (ctx.endpoint or ctx.path) if ctx else "unknown"
        record_http_request(
            method=method,
            endpoint=endpoint,
            status_code=response.status_code,
            duration_seconds=duration,
        )
        return response


__all__ = [
    "generate_latest_metrics",
    "record_ai_insight_cost",
    "record_ai_insight_data_quality",
    "record_ai_insight_generated",
    "record_ai_insight_rejection",
    "record_ai_insight_run",
    "record_ai_insight_runs_purged",
    "record_ai_insight_truncated",
    "record_audit_purge",
    "record_auth_login",
    "record_auth_login_cookie_only_header",
    "record_cache_hit",
    "record_cache_invalidation",
    "record_cache_miss",
    "record_http_request",
    "register_prometheus_middleware",
]
