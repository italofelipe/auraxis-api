from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast, overload
from uuid import UUID

from flask_jwt_extended import get_jwt, verify_jwt_in_request
from flask_jwt_extended.exceptions import NoAuthorizationError

from app.extensions.database import db
from app.models.user import User


class AuthContextError(RuntimeError):
    """Base error for framework-agnostic auth context resolution."""


class InvalidAuthContextError(AuthContextError):
    """Raised when the request carries invalid or incomplete auth claims."""


class RevokedTokenError(AuthContextError):
    """Raised when the token is structurally valid but no longer active."""


class AccountBlockedError(AuthContextError):
    """Raised when a valid identity belongs to a blocked account."""


@dataclass(frozen=True)
class AuthContext:
    subject: str
    email: str | None
    roles: tuple[str, ...]
    permissions: tuple[str, ...]
    jti: str | None
    issued_at: datetime | None
    expires_at: datetime | None
    raw_claims: Mapping[str, object]


def _claim_as_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value.strip() else None


def _claim_as_sequence(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _claim_as_datetime(payload: Mapping[str, object], key: str) -> datetime | None:
    value = payload.get(key)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def auth_context_from_claims(payload: Mapping[str, object]) -> AuthContext:
    subject = _claim_as_str(payload, "sub")
    if subject is None:
        raise InvalidAuthContextError("JWT is missing subject claim.")
    return AuthContext(
        subject=subject,
        email=_claim_as_str(payload, "email"),
        roles=_claim_as_sequence(payload, "roles"),
        permissions=_claim_as_sequence(payload, "permissions"),
        jti=_claim_as_str(payload, "jti"),
        issued_at=_claim_as_datetime(payload, "iat"),
        expires_at=_claim_as_datetime(payload, "exp"),
        raw_claims=payload,
    )


@overload
def get_current_auth_context(*, optional: Literal[False] = False) -> AuthContext: ...


@overload
def get_current_auth_context(*, optional: Literal[True]) -> AuthContext | None: ...


def get_current_auth_context(*, optional: bool = False) -> AuthContext | None:
    return _get_current_auth_context(optional=optional)


def _get_current_auth_context(*, optional: bool) -> AuthContext | None:
    try:
        # Revocation is resolved below against the canonical User record. Keeping
        # framework verification structural here lets us distinguish blocked
        # accounts from ordinary revoked sessions in the public error contract.
        verify_jwt_in_request(optional=optional, skip_revocation_check=True)
    except NoAuthorizationError:
        if optional:
            return None
        raise
    payload = cast(Mapping[str, object], get_jwt())
    if not payload:
        if optional:
            return None
        raise InvalidAuthContextError("JWT payload is empty.")
    return auth_context_from_claims(payload)


@overload
def current_user_id(*, optional: Literal[False] = False) -> UUID: ...


@overload
def current_user_id(*, optional: Literal[True]) -> UUID | None: ...


def current_user_id(*, optional: bool = False) -> UUID | None:
    if optional:
        context = get_current_auth_context(optional=True)
    else:
        context = get_current_auth_context()
    if context is None:
        return None
    try:
        return UUID(context.subject)
    except ValueError as exc:
        raise InvalidAuthContextError("JWT subject is not a valid UUID.") from exc


@overload
def current_token_jti(*, optional: Literal[False] = False) -> str | None: ...


@overload
def current_token_jti(*, optional: Literal[True]) -> str | None: ...


def current_token_jti(*, optional: bool = False) -> str | None:
    if optional:
        context = get_current_auth_context(optional=True)
    else:
        context = get_current_auth_context()
    if context is None:
        return None
    return str(context.jti) if context.jti is not None else None


def _user_from_auth_context(context: AuthContext) -> User | None:
    try:
        user_id = UUID(context.subject)
    except ValueError as exc:
        raise InvalidAuthContextError("JWT subject is not a valid UUID.") from exc
    return cast(User | None, db.session.get(User, user_id))


def is_auth_context_revoked(context: AuthContext) -> bool:
    user = _user_from_auth_context(context)
    if (
        user is None
        or user.deleted_at is not None  # LGPD: soft-deleted accounts are always revoked
        or user.blocked_at is not None
        or context.jti is None
    ):
        return True

    # Match the Flask-JWT-Extended callback semantics even though structural JWT
    # verification intentionally skips that callback. This preserves multi-device
    # sessions while allowing callers to distinguish ACCOUNT_BLOCKED from a normal
    # revoked token.
    from app.application.services.session_service import (
        check_refresh_jti_revoked,
        has_any_session,
        is_access_jti_active,
    )

    token_type = context.raw_claims.get("type", "access")
    if token_type == "refresh":
        refresh_revoked = check_refresh_jti_revoked(
            user_id=user.id,
            jti=context.jti,
        )
        if refresh_revoked is not None:
            return refresh_revoked
        return cast(str | None, user.refresh_token_jti) != context.jti

    if has_any_session(user_id=user.id):
        return not is_access_jti_active(user_id=user.id, jti=context.jti)
    return cast(str | None, user.current_jti) != context.jti


def is_auth_context_blocked(context: AuthContext) -> bool:
    user = _user_from_auth_context(context)
    return user is not None and user.blocked_at is not None


@overload
def get_active_auth_context(*, optional: Literal[False] = False) -> AuthContext: ...


@overload
def get_active_auth_context(*, optional: Literal[True]) -> AuthContext | None: ...


def get_active_auth_context(*, optional: bool = False) -> AuthContext | None:
    if optional:
        context = get_current_auth_context(optional=True)
    else:
        context = get_current_auth_context()
    if context is None:
        return None
    if is_auth_context_blocked(context):
        raise AccountBlockedError("Account is blocked.")
    if is_auth_context_revoked(context):
        raise RevokedTokenError("JWT is revoked.")
    return context


def _get_active_auth_context(*, optional: bool) -> AuthContext | None:
    context = _get_current_auth_context(optional=optional)
    if context is None:
        return None
    if is_auth_context_blocked(context):
        raise AccountBlockedError("Account is blocked.")
    if is_auth_context_revoked(context):
        raise RevokedTokenError("JWT is revoked.")
    return context


@overload
def get_active_user(
    *, optional: Literal[False] = False
) -> tuple[AuthContext, User]: ...


@overload
def get_active_user(*, optional: Literal[True]) -> tuple[AuthContext, User] | None: ...


def get_active_user(*, optional: bool = False) -> tuple[AuthContext, User] | None:
    if optional:
        context = get_active_auth_context(optional=True)
    else:
        context = get_active_auth_context()
    if context is None:
        return None
    user = _user_from_auth_context(context)
    if user is None:
        raise RevokedTokenError("JWT does not resolve to an active user.")
    return context, user
