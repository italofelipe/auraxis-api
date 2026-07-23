"""Canonical auth boundary for HTTP runtimes.

New framework integrations must consume these helpers instead of importing
framework-specific JWT middleware directly. This keeps Flask and FastAPI
coexistence constrained to the adapter layer during the X3 migration.
"""

from .identity import (
    AccountBlockedError,
    AuthContext,
    AuthContextError,
    InvalidAuthContextError,
    RevokedTokenError,
    current_token_jti,
    current_user_id,
    get_active_auth_context,
    get_active_user,
    get_current_auth_context,
    is_auth_context_revoked,
)

__all__ = [
    "AccountBlockedError",
    "AuthContext",
    "AuthContextError",
    "InvalidAuthContextError",
    "RevokedTokenError",
    "current_token_jti",
    "current_user_id",
    "get_active_auth_context",
    "get_active_user",
    "get_current_auth_context",
    "is_auth_context_revoked",
]
