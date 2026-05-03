"""GraphQL resolver-level structured logging.

The audit (2026-05-02) flagged that the GraphQL package emits **zero**
application-level log events. Auth failures, destructive mutations, and
slow resolvers are invisible until something goes wrong in production.

This module provides a thin decorator that wraps a resolver, emitting two
structured events:

- ``graphql.resolver.ok`` on success — info level, includes the
  operation name, the duration, and a hashed user identifier (SHA-256
  truncated to 8 hex chars; never the raw id, never an email).
- ``graphql.resolver.failed`` on exception — warning level, same
  fields plus the error code from the GraphQL extensions when available.

The decorator is intentionally minimal: it does not own metrics emission
(the security middleware already counts requests/violations) and it does
not mutate the resolver's return value. Wider rollout — every resolver,
not just the audit-bearing ones — is tracked under #1142 / umbrella #1157.
"""

from __future__ import annotations

import functools
import hashlib
import time
from typing import Any, Callable, TypeVar

from app.http.runtime import runtime_logger

F = TypeVar("F", bound=Callable[..., Any])


def _hash_user_id(value: Any) -> str | None:
    if value is None:
        return None
    try:
        digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    except Exception:
        return None
    return digest[:8]


def _extract_error_code(exc: BaseException) -> str | None:
    extensions = getattr(exc, "extensions", None)
    if isinstance(extensions, dict):
        code = extensions.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _resolve_actor_hash() -> str | None:
    # Imported lazily to avoid eager Flask context loading at module import
    # time; the helper itself is tolerant of missing context.
    from app.graphql.auth import get_current_user_optional

    try:
        user = get_current_user_optional()
    except Exception:
        return None
    if user is None:
        return None
    return _hash_user_id(getattr(user, "id", None))


def log_graphql_resolver(operation_name: str) -> Callable[[F], F]:
    """Decorator wrapping a Graphene mutation/query resolver to emit a single
    structured log event per invocation.

    ``operation_name`` is the canonical event identifier — choose the
    GraphQL field name (``deleteGoal``, ``cancelSubscription``, ...).
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                runtime_logger().warning(
                    "graphql.resolver.failed operation=%s code=%s "
                    "duration_ms=%d user_hash=%s",
                    operation_name,
                    _extract_error_code(exc) or "n/a",
                    duration_ms,
                    _resolve_actor_hash() or "anonymous",
                )
                raise
            duration_ms = int((time.monotonic() - start) * 1000)
            runtime_logger().info(
                "graphql.resolver.ok operation=%s duration_ms=%d user_hash=%s",
                operation_name,
                duration_ms,
                _resolve_actor_hash() or "anonymous",
            )
            return result

        return wrapper  # type: ignore[return-value]

    return decorator
