from typing import Any, Dict
from uuid import UUID

from flask import g, jsonify
from flask.typing import ResponseReturnValue
from flask_jwt_extended import JWTManager

from app.auth import InvalidAuthContextError, current_user_id
from app.extensions.database import db
from app.extensions.jwt_revocation_cache import get_jwt_revocation_cache
from app.models.user import User
from app.utils.api_contract import is_v2_contract_request
from app.utils.response_builder import error_payload


def _jwt_error_response(
    message: str, *, code: str, status_code: int
) -> ResponseReturnValue:
    if is_v2_contract_request():
        return (
            jsonify(error_payload(message=message, code=code, details={})),
            status_code,
        )
    return jsonify({"message": message}), status_code


def is_token_revoked(jti: str) -> bool:
    # Keep compatibility with legacy call sites that still invoke this helper.
    # Runtime revocation source-of-truth is persisted in user.current_jti.
    try:
        identity = current_user_id(optional=True)
        if identity is None:
            return True
        user = db.session.get(User, identity)
        if user and user.blocked_at is not None:
            g.account_blocked = True
        return (
            not user
            or user.deleted_at is not None
            or user.blocked_at is not None
            or user.current_jti != jti
        )
    except InvalidAuthContextError:
        return True


def _is_access_token_revoked_multi_session(user_id: str, jti: str) -> bool | None:
    """Check multi-device access-token revocation via the RefreshToken table.

    Returns None if the session predates the RefreshToken table (no row found),
    signalling to the caller to fall back to the user.current_jti path.
    """
    from app.application.services.session_service import (
        has_any_session,
        is_access_jti_active,
    )

    try:
        uid = UUID(user_id)
        active = is_access_jti_active(user_id=uid, jti=jti)
        if active:
            return False  # Definitely active → not revoked.
        if has_any_session(user_id=uid):
            return True  # Rows exist but this JTI is not among them → revoked.
        return None  # No rows — fall back to user.current_jti.
    except Exception:
        return None  # Defensive: fall back on any error.


def _is_access_token_revoked(user_id: str, jti: str) -> bool:
    """Check access token revocation using Redis cache (DB fallback on miss).

    H-1028: Multi-device sessions.  When the user has RefreshToken rows,
    revocation is checked per-session (current_access_jti).  Falls back to
    the legacy single-session user.current_jti path for old sessions.

    Side-effect: sets ``g.session_displaced = True`` for the legacy path.
    """
    # A block operation deletes this cache entry before returning. Preserve the
    # established hot path for active legacy sessions; a miss revalidates the
    # canonical user row and repopulates only after the blocked/deleted checks.
    cache = get_jwt_revocation_cache()
    cached_jti = cache.get_current_jti(user_id)
    if cached_jti is not None:
        displaced = cached_jti != jti
        if displaced:
            g.session_displaced = True
        return displaced

    user = db.session.get(User, UUID(user_id))
    if not user or user.deleted_at is not None:
        return True
    if user.blocked_at is not None:
        g.account_blocked = True
        return True

    # Multi-device fast path — try RefreshToken table first.
    multi = _is_access_token_revoked_multi_session(user_id, jti)
    if multi is not None:
        return multi

    # Legacy single-session path (no RefreshToken rows for this user).
    cache.set_current_jti(user_id, user.current_jti)
    if user.current_jti != jti:
        # current_jti is non-null → another session replaced this one
        if user.current_jti is not None:
            g.session_displaced = True
        return True
    return False


def _is_refresh_token_revoked(user_id: str, jti: str) -> bool:
    """Check refresh token revocation against the DB.

    H-1028: checks the RefreshToken table first (with family revocation on
    reuse); falls back to user.refresh_token_jti for sessions without rows.
    """
    user = db.session.get(User, UUID(user_id))
    if not user or user.deleted_at is not None:  # LGPD: soft-deleted = revoked
        return True
    if user.blocked_at is not None:
        g.account_blocked = True
        return True

    from app.application.services.session_service import check_refresh_jti_revoked

    result = check_refresh_jti_revoked(user_id=UUID(user_id), jti=jti)
    if result is not None:
        return result

    # Fallback: legacy user.refresh_token_jti field.
    return bool(user.refresh_token_jti != jti)


def register_jwt_callbacks(jwt: JWTManager) -> None:
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(
        jwt_header: Dict[str, Any], jwt_payload: Dict[str, Any]
    ) -> bool:
        user_id = jwt_payload.get("sub")
        jti = jwt_payload.get("jti")
        token_type = jwt_payload.get("type", "access")

        if not user_id or not jti:
            return True

        if token_type == "refresh":
            return _is_refresh_token_revoked(user_id, jti)
        return _is_access_token_revoked(user_id, jti)

    @jwt.revoked_token_loader
    def revoked_token_callback(
        jwt_header: Dict[str, Any], jwt_payload: Dict[str, Any]
    ) -> Any:
        # H-P5.3 — single-session policy feedback:
        # SESSION_DISPLACED → another device logged in (current_jti replaced).
        # SESSION_REVOKED   → explicit logout or account erasure.
        if getattr(g, "account_blocked", False):
            return _jwt_error_response(
                "Conta bloqueada. Entre em contato com o suporte.",
                code="ACCOUNT_BLOCKED",
                status_code=403,
            )
        if getattr(g, "session_displaced", False):
            return _jwt_error_response(
                "Sua sessão foi encerrada porque você entrou em outro dispositivo.",
                code="SESSION_DISPLACED",
                status_code=401,
            )
        return _jwt_error_response(
            "Sessão encerrada. Faça login novamente.",
            code="SESSION_REVOKED",
            status_code=401,
        )

    @jwt.invalid_token_loader
    def invalid_token_callback(error: str) -> Any:
        return _jwt_error_response(
            "Token inválido",
            code="UNAUTHORIZED",
            status_code=401,
        )

    @jwt.expired_token_loader
    def expired_token_callback(
        jwt_header: Dict[str, Any], jwt_payload: Dict[str, Any]
    ) -> Any:
        return _jwt_error_response(
            "Token expirado",
            code="UNAUTHORIZED",
            status_code=401,
        )

    @jwt.unauthorized_loader
    def missing_token_callback(error: str) -> Any:
        return _jwt_error_response(
            "Token ausente",
            code="UNAUTHORIZED",
            status_code=401,
        )
