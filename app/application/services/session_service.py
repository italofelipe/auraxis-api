"""Session management for multi-device refresh token rotation (#1028).

Responsibilities:
- Create a RefreshToken record on login (enforcing max-sessions limit).
- Rotate a refresh token: validate, detect theft, create new record.
- Revoke a specific session or all sessions for a user.
- List active sessions for a user.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta
from typing import TypedDict
from uuid import UUID

from app.extensions.database import db
from app.models.refresh_token import _MAX_SESSIONS_PER_USER, RefreshToken
from app.utils.datetime_utils import utc_now_naive

_REFRESH_TOKEN_TTL_DAYS = 30
_MAX_SESSIONS = int(os.getenv("MAX_SESSIONS_PER_USER", str(_MAX_SESSIONS_PER_USER)))

# Grace window for refresh-token reuse detection. A client booting/reloading can
# fire two concurrent POST /auth/refresh with the same (still-old) cookie before
# the rotated cookie propagates. The loser presents a token that was revoked a
# fraction of a second ago — that is a benign concurrent refresh, NOT a stolen
# token replayed minutes later. Within this window we reject the loser softly
# (ConcurrentRefreshError) without nuking the whole token family; outside it we
# treat reuse as theft and revoke the family.
_REUSE_GRACE_SECONDS = int(os.getenv("AURAXIS_REFRESH_REUSE_GRACE_SECONDS", "15"))


class SessionInfo(TypedDict):
    id: str
    device_info: dict[str, str]
    created_at: str
    expires_at: str
    is_current: bool


class SessionNotFoundError(Exception):
    """Raised when a session cannot be found or does not belong to the user."""


class TokenReuseError(Exception):
    """Raised when a revoked refresh token is presented (possible theft)."""


class ConcurrentRefreshError(Exception):
    """Raised when a just-rotated refresh token is presented again within the
    reuse grace window — a benign concurrent refresh (e.g. boot/F5 double-submit
    or a second tab). The request is rejected softly: the token family is NOT
    revoked, so the winning refresh and other sessions stay valid."""


def _is_within_reuse_grace(revoked_at: datetime) -> bool:
    """True when *revoked_at* is recent enough to be a benign concurrent refresh."""
    return utc_now_naive() - revoked_at <= timedelta(seconds=_REUSE_GRACE_SECONDS)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _build_device_info(
    *, user_agent: str | None, remote_addr: str | None
) -> dict[str, str]:  # noqa: E501
    partial_ip = ""
    if remote_addr:
        # Keep only the first two octets of IPv4 (or first group of IPv6).
        parts = remote_addr.split(".")
        partial_ip = (
            ".".join(parts[:2]) + ".x.x"
            if len(parts) == 4
            else remote_addr.split(":")[0]
        )  # noqa: E501
    return {
        "user_agent": (user_agent or "")[:512],
        "ip_prefix": partial_ip,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_session(
    *,
    user_id: UUID,
    raw_refresh_token: str,
    refresh_jti: str,
    access_jti: str,
    user_agent: str | None = None,
    remote_addr: str | None = None,
) -> RefreshToken:
    """Create a RefreshToken row on a successful login.

    Evicts the oldest active session when the per-user limit is exceeded.
    """
    token_hash = _hash_token(raw_refresh_token)
    family_id = uuid.uuid4()
    expires_at = utc_now_naive() + timedelta(days=_REFRESH_TOKEN_TTL_DAYS)
    device_info = _build_device_info(user_agent=user_agent, remote_addr=remote_addr)

    # Enforce session limit — evict oldest by created_at.
    active = (
        RefreshToken.query.filter_by(user_id=user_id)
        .filter(RefreshToken.revoked_at.is_(None))
        .filter(RefreshToken.expires_at > utc_now_naive())
        .order_by(RefreshToken.created_at.asc())
        .all()
    )
    overflow = len(active) - (_MAX_SESSIONS - 1)
    for old in active[: max(0, overflow)]:
        old.revoke()

    session = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        jti=refresh_jti,
        current_access_jti=access_jti,
        family_id=family_id,
        device_info=device_info,
        expires_at=expires_at,
    )
    db.session.add(session)
    db.session.flush()
    return session


def rotate_session(
    *,
    raw_refresh_token: str,
    new_raw_refresh_token: str,
    new_refresh_jti: str,
    new_access_jti: str,
    user_agent: str | None = None,
    remote_addr: str | None = None,
) -> RefreshToken:
    """Rotate a refresh token identified by its raw value (token_hash lookup).

    1. Find the existing record by token_hash.
    2. If found but revoked → family-wide revocation (token theft detected).
    3. If found and active → revoke old, create new in the same family.
    4. If not found → raise SessionNotFoundError.

    Returns the newly created RefreshToken record.
    """
    token_hash = _hash_token(raw_refresh_token)
    existing: RefreshToken | None = RefreshToken.query.filter_by(
        token_hash=token_hash
    ).first()

    if existing is None:
        raise SessionNotFoundError("Refresh token not found.")

    if existing.revoked_at is not None:
        if _is_within_reuse_grace(existing.revoked_at):
            # Benign concurrent refresh — reject softly, keep the family alive.
            raise ConcurrentRefreshError(
                "Concurrent refresh — token rotated moments ago."
            )
        # Token reuse detected — revoke the entire family.
        _revoke_family(existing.family_id)
        raise TokenReuseError(
            "Refresh token already used — possible theft detected. "
            "All sessions in this family have been revoked."
        )

    if existing.expires_at <= utc_now_naive():
        raise SessionNotFoundError("Refresh token expired.")

    family_id = existing.family_id
    user_id = existing.user_id
    device_info = _build_device_info(user_agent=user_agent, remote_addr=remote_addr)

    existing.revoke()

    new_hash = _hash_token(new_raw_refresh_token)
    new_session = RefreshToken(
        user_id=user_id,
        token_hash=new_hash,
        jti=new_refresh_jti,
        current_access_jti=new_access_jti,
        family_id=family_id,
        device_info=device_info,
        expires_at=utc_now_naive() + timedelta(days=_REFRESH_TOKEN_TTL_DAYS),
    )
    db.session.add(new_session)
    db.session.flush()
    return new_session


def rotate_session_by_jti(
    *,
    old_jti: str,
    new_raw_refresh_token: str,
    new_refresh_jti: str,
    new_access_jti: str,
    user_agent: str | None = None,
    remote_addr: str | None = None,
) -> RefreshToken | None:
    """Rotate a refresh token identified by JTI (for use after JWT validation).

    This variant is used by the refresh endpoint where the JWT has already been
    validated by Flask-JWT-Extended.  Returns None if no RefreshToken row
    exists for this JTI (backward-compat: old sessions without rows).
    """
    existing: RefreshToken | None = RefreshToken.query.filter_by(jti=old_jti).first()
    if existing is None:
        return None  # Caller falls back to user.refresh_token_jti path.

    # Revocation check is already done by @jwt_required(refresh=True), but
    # handle the edge case defensively.
    if existing.revoked_at is not None:
        if _is_within_reuse_grace(existing.revoked_at):
            # Benign concurrent refresh (boot/F5 double-submit) — reject softly
            # without revoking the family so the winning session stays valid.
            raise ConcurrentRefreshError(
                "Concurrent refresh — token rotated moments ago."
            )
        _revoke_family(existing.family_id)
        raise TokenReuseError("Refresh token already used — possible theft detected.")

    if existing.expires_at <= utc_now_naive():
        raise SessionNotFoundError("Refresh token expired.")

    family_id = existing.family_id
    user_id = existing.user_id
    device_info = _build_device_info(user_agent=user_agent, remote_addr=remote_addr)
    existing.revoke()

    new_hash = _hash_token(new_raw_refresh_token)
    new_session = RefreshToken(
        user_id=user_id,
        token_hash=new_hash,
        jti=new_refresh_jti,
        current_access_jti=new_access_jti,
        family_id=family_id,
        device_info=device_info,
        expires_at=utc_now_naive() + timedelta(days=_REFRESH_TOKEN_TTL_DAYS),
    )
    db.session.add(new_session)
    db.session.flush()
    return new_session


def check_refresh_jti_revoked(*, user_id: UUID, jti: str) -> bool | None:
    """Return True if *jti* is revoked, False if active, None to fall back.

    Used by the JWT revocation callback. ``None`` signals the caller to
    fall back to ``user.refresh_token_jti``. ``user_id`` is accepted to
    preserve the public signature even though the lookup is by ``jti``;
    discarded explicitly so unused-argument linters stay silent.
    """
    del user_id
    existing: RefreshToken | None = RefreshToken.query.filter_by(jti=jti).first()
    if existing is None:
        return None  # Fall back to user field.
    if existing.revoked_at is not None:
        _revoke_family(existing.family_id)
        db.session.commit()
        return True
    if existing.expires_at <= utc_now_naive():
        return True
    return False


def revoke_session(*, session_id: UUID, user_id: UUID) -> None:
    """Revoke a specific session belonging to *user_id*."""
    session: RefreshToken | None = db.session.get(RefreshToken, session_id)
    if session is None or session.user_id != user_id:
        raise SessionNotFoundError("Session not found.")
    session.revoke()
    db.session.commit()


def revoke_all_sessions(*, user_id: UUID) -> int:
    """Revoke all active sessions for *user_id*. Returns number revoked."""
    now = utc_now_naive()
    active = (
        RefreshToken.query.filter_by(user_id=user_id)
        .filter(RefreshToken.revoked_at.is_(None))
        .filter(RefreshToken.expires_at > now)
        .all()
    )
    for s in active:
        s.revoke()
    db.session.commit()
    return len(active)


def list_sessions(
    *, user_id: UUID, current_access_jti: str | None = None
) -> list[SessionInfo]:  # noqa: E501
    """Return active sessions for *user_id*, marking the current one."""
    now = utc_now_naive()
    sessions = (
        RefreshToken.query.filter_by(user_id=user_id)
        .filter(RefreshToken.revoked_at.is_(None))
        .filter(RefreshToken.expires_at > now)
        .order_by(RefreshToken.created_at.desc())
        .all()
    )
    return [
        SessionInfo(
            id=str(s.id),
            device_info=dict(s.device_info or {}),
            created_at=_fmt(s.created_at),
            expires_at=_fmt(s.expires_at),
            is_current=(
                current_access_jti is not None
                and s.current_access_jti == current_access_jti
            ),
        )
        for s in sessions
    ]


def has_any_session(*, user_id: UUID) -> bool:
    """Return True if *user_id* has at least one RefreshToken row (any state).

    Used to detect whether this user has migrated to the multi-device table.
    """
    return (
        db.session.query(RefreshToken.id).filter_by(user_id=user_id).first() is not None
    )


def is_access_jti_active(*, user_id: UUID, jti: str) -> bool:
    """Return True if *jti* belongs to an active session for *user_id*.

    Used by the JWT revocation check to support multi-device access tokens.
    """
    now = utc_now_naive()
    return (
        db.session.query(RefreshToken.id)
        .filter_by(user_id=user_id, current_access_jti=jti)
        .filter(RefreshToken.revoked_at.is_(None))
        .filter(RefreshToken.expires_at > now)
        .first()
        is not None
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _revoke_family(family_id: uuid.UUID) -> None:
    now = utc_now_naive()
    members = (
        RefreshToken.query.filter_by(family_id=family_id)
        .filter(RefreshToken.revoked_at.is_(None))
        .all()
    )
    for m in members:
        m.revoked_at = now


def _fmt(dt: datetime) -> str:
    return dt.isoformat() if dt else ""


__all__ = [
    "SessionInfo",
    "ConcurrentRefreshError",
    "SessionNotFoundError",
    "TokenReuseError",
    "check_refresh_jti_revoked",
    "create_session",
    "has_any_session",
    "is_access_jti_active",
    "list_sessions",
    "revoke_all_sessions",
    "revoke_session",
    "rotate_session",
    "rotate_session_by_jti",
]
