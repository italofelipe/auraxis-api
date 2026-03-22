from __future__ import annotations

import hashlib
import secrets
from typing import cast

from werkzeug.security import check_password_hash

_DUMMY_SALT = secrets.token_bytes(16)
_DUMMY_PBKDF2_ITERATIONS = 600_000


def _burn_hash_cycles(plain_password: str) -> None:
    hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        _DUMMY_SALT,
        _DUMMY_PBKDF2_ITERATIONS,
    )


def verify_password_with_timing_protection(
    *,
    password_hash: str | None,
    plain_password: str,
) -> bool:
    """Verify password while reducing user-existence timing signal.

    When a user is not found, we still execute one password-hash check against a
    static dummy hash so invalid logins have a closer runtime profile.
    """

    if password_hash:
        return cast(bool, check_password_hash(password_hash, plain_password))

    _burn_hash_cycles(plain_password)
    return False
