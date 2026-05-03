"""Correlation-ID middleware — Sentry tagging and structured log injection.

Builds on top of ``app.http.request_context`` (which assigns and echoes the
request-id) to close the remaining observability gaps:

1. **Sentry tag** — ``request_id`` is set on every Sentry event so backend and
   frontend errors can be correlated by the same ID.
2. **Log record factory** — every ``logging.LogRecord`` carries a
   ``request_id`` attribute so formatters can include it without coupling
   business code to Flask.

Register via ``register_correlation_id(app)`` inside ``_register_http_runtime``.
Nginx must forward ``X-Request-ID $request_id;`` so the ID originates there.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from flask import Flask, g, has_request_context

_NOOP_REQUEST_ID = "n/a"


def _current_request_id() -> str:
    if not has_request_context():
        return _NOOP_REQUEST_ID
    return str(getattr(g, "request_id", None) or _NOOP_REQUEST_ID)


_CORRELATION_FACTORY_MARK = "_auraxis_correlation_factory"


def _make_log_record_factory(
    original: Callable[..., logging.LogRecord],
) -> Callable[..., logging.LogRecord]:
    def _factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = original(*args, **kwargs)
        record.request_id = _current_request_id()
        return record

    setattr(_factory, _CORRELATION_FACTORY_MARK, True)
    return _factory


def _inject_sentry_tag(request_id: str) -> None:
    if not os.getenv("SENTRY_DSN", "").strip():
        return
    try:
        import sentry_sdk

        sentry_sdk.set_tag("request_id", request_id)
    except Exception:  # noqa: BLE001
        pass


def register_correlation_id(app: Flask) -> None:
    """Wire up Sentry tagging and log-record injection for every request.

    The log-record factory is wrapped exactly once per process. Calling
    ``register_correlation_id`` multiple times (e.g. one Flask app per
    pytest test) is safe — without the idempotency check, each call would
    nest a new wrapper around the previous one, eventually exceeding
    Python's recursion limit during ``logger.info`` and bringing the test
    suite down.
    """
    original_factory = logging.getLogRecordFactory()
    if not getattr(original_factory, _CORRELATION_FACTORY_MARK, False):
        logging.setLogRecordFactory(_make_log_record_factory(original_factory))

    @app.before_request
    def _tag_sentry() -> None:
        _inject_sentry_tag(_current_request_id())
