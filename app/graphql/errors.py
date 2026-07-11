from __future__ import annotations

from typing import Any

from graphql import GraphQLError

from app.application.services.public_error_mapper_service import (
    map_validation_exception,
)

GRAPHQL_ERROR_CODE_AUTH_BACKEND_UNAVAILABLE = "AUTH_BACKEND_UNAVAILABLE"
GRAPHQL_ERROR_CODE_CONFLICT = "CONFLICT"
GRAPHQL_ERROR_CODE_FORBIDDEN = "FORBIDDEN"
GRAPHQL_ERROR_CODE_NOT_FOUND = "NOT_FOUND"
GRAPHQL_ERROR_CODE_TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
GRAPHQL_ERROR_CODE_UNAUTHORIZED = "UNAUTHORIZED"
GRAPHQL_ERROR_CODE_VALIDATION = "VALIDATION_ERROR"
# AI governance codes (#1546) — REST parity for quota/entitlement/budget/consent.
GRAPHQL_ERROR_CODE_AI_DAILY_LIMIT = "AI_DAILY_LIMIT_EXCEEDED"
GRAPHQL_ERROR_CODE_AI_BUDGET = "AI_INSIGHT_BUDGET_EXCEEDED"
GRAPHQL_ERROR_CODE_ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
GRAPHQL_ERROR_CODE_AI_CONSENT_REQUIRED = "AI_CONSENT_REQUIRED"

PUBLIC_GRAPHQL_ERROR_CODES = frozenset(
    {
        GRAPHQL_ERROR_CODE_AUTH_BACKEND_UNAVAILABLE,
        GRAPHQL_ERROR_CODE_CONFLICT,
        GRAPHQL_ERROR_CODE_FORBIDDEN,
        GRAPHQL_ERROR_CODE_NOT_FOUND,
        GRAPHQL_ERROR_CODE_TOO_MANY_ATTEMPTS,
        GRAPHQL_ERROR_CODE_UNAUTHORIZED,
        GRAPHQL_ERROR_CODE_VALIDATION,
        GRAPHQL_ERROR_CODE_AI_DAILY_LIMIT,
        GRAPHQL_ERROR_CODE_AI_BUDGET,
        GRAPHQL_ERROR_CODE_ENTITLEMENT_REQUIRED,
        GRAPHQL_ERROR_CODE_AI_CONSENT_REQUIRED,
    }
)


def to_public_graphql_code(code: str | None) -> str:
    normalized = str(code or "").strip().upper()
    if normalized in PUBLIC_GRAPHQL_ERROR_CODES:
        return normalized
    return GRAPHQL_ERROR_CODE_VALIDATION


def build_public_graphql_error(
    message: str,
    *,
    code: str,
    retry_after_seconds: int | None = None,
) -> GraphQLError:
    extensions: dict[str, Any] = {"code": to_public_graphql_code(code)}
    if retry_after_seconds is not None:
        extensions["retry_after_seconds"] = int(retry_after_seconds)
    return GraphQLError(message, extensions=extensions)


def from_mapped_validation_exception(
    exc: Exception,
    *,
    fallback_message: str,
) -> GraphQLError:
    mapped = map_validation_exception(exc, fallback_message=fallback_message)
    return build_public_graphql_error(
        mapped.message,
        code=to_public_graphql_code(mapped.code),
    )
