"""Local account block/unblock primitives used by administrative control planes."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from app.extensions.database import db
from app.extensions.jwt_revocation_cache import get_jwt_revocation_cache
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.utils.datetime_utils import utc_now_naive


class AccountControlError(ValueError):
    pass


def block_user(*, user_id: UUID, reason: str, blocked_by: str) -> User:
    user = cast(User | None, db.session.get(User, user_id))
    if user is None:
        raise AccountControlError("User not found")
    if user.deleted_at is not None:
        raise AccountControlError("Deleted users cannot be blocked")

    now = utc_now_naive()
    user.blocked_at = user.blocked_at or now
    user.blocked_reason = reason
    user.blocked_by = blocked_by
    user.current_jti = None
    user.refresh_token_jti = None
    RefreshToken.query.filter_by(user_id=user_id).filter(
        RefreshToken.revoked_at.is_(None)
    ).update({RefreshToken.revoked_at: now}, synchronize_session=False)
    db.session.flush()
    get_jwt_revocation_cache().invalidate(str(user_id))
    return user


def unblock_user(*, user_id: UUID) -> User:
    user = cast(User | None, db.session.get(User, user_id))
    if user is None:
        raise AccountControlError("User not found")
    if user.deleted_at is not None:
        raise AccountControlError("Deleted users cannot be unblocked")
    user.blocked_at = None
    user.blocked_reason = None
    user.blocked_by = None
    db.session.flush()
    get_jwt_revocation_cache().invalidate(str(user_id))
    return user


__all__ = ["AccountControlError", "block_user", "unblock_user"]
