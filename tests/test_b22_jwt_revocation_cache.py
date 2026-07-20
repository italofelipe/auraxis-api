"""Tests for B22 — Redis cache for JWT revocation check.

Covers:
- Cache hit: second call does not hit DB (mock DB, assert 1 DB query for 2 checks)
- Cache miss: DB queried, cache populated
- Cache invalidation: after logout, cache key is deleted
- Redis unavailable: falls back to DB without raising an exception
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

from app.extensions.jwt_revocation_cache import (
    RedisJwtRevocationCache,
    _NoOpJwtRevocationCache,
    reset_jwt_revocation_cache_for_tests,
)

# ---------------------------------------------------------------------------
# Unit tests — RedisJwtRevocationCache
# ---------------------------------------------------------------------------


class TestRedisJwtRevocationCache:
    def _make_cache(self, client: Any) -> RedisJwtRevocationCache:
        return RedisJwtRevocationCache(
            client, key_prefix="jwt:revoked", ttl_seconds=300
        )

    def test_get_returns_none_on_redis_miss(self) -> None:
        client = MagicMock()
        client.get.return_value = None
        cache = self._make_cache(client)
        assert cache.get_current_jti("user-1") is None
        client.get.assert_called_once_with("jwt:revoked:user-1")

    def test_get_returns_decoded_string(self) -> None:
        client = MagicMock()
        client.get.return_value = b"abc-jti-value"
        cache = self._make_cache(client)
        assert cache.get_current_jti("user-1") == "abc-jti-value"

    def test_set_calls_setex_with_ttl(self) -> None:
        client = MagicMock()
        cache = self._make_cache(client)
        cache.set_current_jti("user-1", "my-jti")
        client.setex.assert_called_once_with("jwt:revoked:user-1", 300, "my-jti")

    def test_set_none_calls_invalidate(self) -> None:
        client = MagicMock()
        cache = self._make_cache(client)
        cache.set_current_jti("user-1", None)
        client.delete.assert_called_once_with("jwt:revoked:user-1")
        client.setex.assert_not_called()

    def test_invalidate_calls_delete(self) -> None:
        client = MagicMock()
        cache = self._make_cache(client)
        cache.invalidate("user-1")
        client.delete.assert_called_once_with("jwt:revoked:user-1")

    def test_get_returns_none_on_redis_exception(self) -> None:
        client = MagicMock()
        client.get.side_effect = OSError("connection refused")
        cache = self._make_cache(client)
        # Must not raise — should behave as cache miss.
        result = cache.get_current_jti("user-1")
        assert result is None

    def test_set_swallows_redis_exception(self) -> None:
        client = MagicMock()
        client.setex.side_effect = OSError("connection refused")
        cache = self._make_cache(client)
        # Must not raise.
        cache.set_current_jti("user-1", "some-jti")

    def test_invalidate_swallows_redis_exception(self) -> None:
        client = MagicMock()
        client.delete.side_effect = OSError("connection refused")
        cache = self._make_cache(client)
        # Must not raise.
        cache.invalidate("user-1")


class TestNoOpJwtRevocationCache:
    def test_get_always_returns_none(self) -> None:
        cache = _NoOpJwtRevocationCache()
        assert cache.get_current_jti("user-1") is None

    def test_set_is_harmless(self) -> None:
        cache = _NoOpJwtRevocationCache()
        cache.set_current_jti("user-1", "jti-value")  # should not raise

    def test_invalidate_is_harmless(self) -> None:
        cache = _NoOpJwtRevocationCache()
        cache.invalidate("user-1")  # should not raise


# ---------------------------------------------------------------------------
# Unit tests — cache singleton builder
# ---------------------------------------------------------------------------


class TestGetJwtRevocationCache:
    def setup_method(self) -> None:
        reset_jwt_revocation_cache_for_tests()

    def teardown_method(self) -> None:
        reset_jwt_revocation_cache_for_tests()

    def test_returns_noop_when_redis_url_missing(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("JWT_REVOCATION_REDIS_URL", raising=False)
        from app.extensions.jwt_revocation_cache import get_jwt_revocation_cache

        cache = get_jwt_revocation_cache()
        assert isinstance(cache, _NoOpJwtRevocationCache)

    def test_returns_noop_when_redis_unreachable(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:19999")

        fake_redis_cls = MagicMock()
        fake_client = MagicMock()
        fake_client.ping.side_effect = OSError("refused")
        fake_redis_cls.from_url.return_value = fake_client

        fake_module = MagicMock()
        fake_module.Redis = fake_redis_cls

        with patch("importlib.import_module", return_value=fake_module):
            from app.extensions.jwt_revocation_cache import get_jwt_revocation_cache

            cache = get_jwt_revocation_cache()

        assert isinstance(cache, _NoOpJwtRevocationCache)

    def test_returns_redis_cache_when_redis_available(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379")

        fake_redis_cls = MagicMock()
        fake_client = MagicMock()
        fake_client.ping.return_value = True
        fake_redis_cls.from_url.return_value = fake_client

        fake_module = MagicMock()
        fake_module.Redis = fake_redis_cls

        with patch("importlib.import_module", return_value=fake_module):
            from app.extensions.jwt_revocation_cache import get_jwt_revocation_cache

            cache = get_jwt_revocation_cache()

        assert isinstance(cache, RedisJwtRevocationCache)

    def test_singleton_is_reused(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("JWT_REVOCATION_REDIS_URL", raising=False)
        from app.extensions.jwt_revocation_cache import get_jwt_revocation_cache

        c1 = get_jwt_revocation_cache()
        c2 = get_jwt_revocation_cache()
        assert c1 is c2


# ---------------------------------------------------------------------------
# Integration tests — check_if_token_revoked with cache
# ---------------------------------------------------------------------------

# Ensure the module is imported before patching so the attribute exists.
import app.extensions.jwt_callbacks as _jwt_callbacks_mod  # noqa: E402


def _make_jwt_manager_and_capture() -> tuple[Any, dict[str, Any]]:
    jwt_manager = MagicMock()
    captured: dict[str, Any] = {}

    def token_in_blocklist_loader(fn: Any) -> Any:
        captured["fn"] = fn
        return fn

    jwt_manager.token_in_blocklist_loader = token_in_blocklist_loader
    jwt_manager.revoked_token_loader = lambda fn: fn
    jwt_manager.invalid_token_loader = lambda fn: fn
    jwt_manager.expired_token_loader = lambda fn: fn
    jwt_manager.unauthorized_loader = lambda fn: fn
    return jwt_manager, captured


class TestCheckIfTokenRevokedWithCache:
    """Tests that register_jwt_callbacks correctly uses the cache."""

    def test_cache_hit_avoids_db_query(self) -> None:
        """When cache holds the current JTI, db.session.get must NOT be called."""
        user_id = str(uuid.uuid4())
        stored_jti = "correct-jti"

        redis_client = MagicMock()
        redis_client.get.return_value = stored_jti.encode()
        cache = RedisJwtRevocationCache(redis_client)

        jwt_manager, captured = _make_jwt_manager_and_capture()

        _get_cache = patch.object(
            _jwt_callbacks_mod, "get_jwt_revocation_cache", return_value=cache
        )
        with _get_cache, patch.object(_jwt_callbacks_mod, "db") as mock_db:
            _jwt_callbacks_mod.register_jwt_callbacks(jwt_manager)
            check_fn = captured["fn"]

            # First call — cache hit, correct JTI.
            result1 = check_fn(
                {}, {"sub": user_id, "jti": stored_jti, "type": "access"}
            )
            # Second call — same.
            result2 = check_fn(
                {}, {"sub": user_id, "jti": stored_jti, "type": "access"}
            )

        assert result1 is False
        assert result2 is False
        # DB must never be consulted when cache has data.
        mock_db.session.get.assert_not_called()

    def test_cache_miss_queries_db_and_populates_cache(self) -> None:
        """On cache miss the DB is queried and the cache is populated."""
        user_id = str(uuid.uuid4())
        stored_jti = "correct-jti"

        redis_client = MagicMock()
        redis_client.get.return_value = None  # cache miss
        cache = RedisJwtRevocationCache(redis_client)

        mock_user = MagicMock()
        mock_user.current_jti = stored_jti
        mock_user.deleted_at = None  # active user
        mock_user.blocked_at = None

        jwt_manager, captured = _make_jwt_manager_and_capture()

        _get_cache = patch.object(
            _jwt_callbacks_mod, "get_jwt_revocation_cache", return_value=cache
        )
        with (
            _get_cache,
            patch.object(_jwt_callbacks_mod, "db") as mock_db,
            patch.object(_jwt_callbacks_mod, "UUID", side_effect=uuid.UUID),
        ):
            mock_db.session.get.return_value = mock_user

            _jwt_callbacks_mod.register_jwt_callbacks(jwt_manager)
            check_fn = captured["fn"]

            result = check_fn({}, {"sub": user_id, "jti": stored_jti, "type": "access"})

        assert result is False
        mock_db.session.get.assert_called_once()
        # Cache should now be populated.
        redis_client.setex.assert_called_once()

    def test_redis_unavailable_falls_back_to_db(self) -> None:
        """When Redis is unavailable (no-op cache), the DB is queried without error."""
        user_id = str(uuid.uuid4())
        stored_jti = "correct-jti"

        noop_cache = _NoOpJwtRevocationCache()
        mock_user = MagicMock()
        mock_user.current_jti = stored_jti
        mock_user.deleted_at = None  # active user
        mock_user.blocked_at = None

        jwt_manager, captured = _make_jwt_manager_and_capture()

        with (
            patch.object(
                _jwt_callbacks_mod, "get_jwt_revocation_cache", return_value=noop_cache
            ),
            patch.object(_jwt_callbacks_mod, "db") as mock_db,
            patch.object(_jwt_callbacks_mod, "UUID", side_effect=uuid.UUID),
        ):
            mock_db.session.get.return_value = mock_user

            _jwt_callbacks_mod.register_jwt_callbacks(jwt_manager)
            check_fn = captured["fn"]

            # Must not raise even though cache is a no-op.
            result = check_fn({}, {"sub": user_id, "jti": stored_jti, "type": "access"})

        assert result is False
        mock_db.session.get.assert_called_once()


# ---------------------------------------------------------------------------
# Unit tests — SESSION_DISPLACED flag (H-P5.3 single-session policy)
# ---------------------------------------------------------------------------


class TestSessionDisplacedFlag:
    """Verify that g.session_displaced is set when a session is replaced."""

    def _run_check(
        self, *, app: Any, cache: Any, user_id: str, jti: str, mock_user: Any = None
    ) -> bool:
        """Run _is_access_token_revoked inside an app context and return the result."""
        import app.extensions.jwt_callbacks as _m

        with app.app_context():
            with patch.object(_m, "get_jwt_revocation_cache", return_value=cache):
                if mock_user is not None:
                    with (
                        patch.object(_m, "db") as mock_db,
                        patch.object(_m, "UUID", side_effect=uuid.UUID),
                    ):
                        mock_db.session.get.return_value = mock_user
                        return _m._is_access_token_revoked(user_id, jti)
                else:
                    return _m._is_access_token_revoked(user_id, jti)

    def test_session_displaced_set_on_cache_hit_with_different_jti(
        self, app: Any
    ) -> None:
        """Cache hit with a different (newer) JTI → session was displaced."""
        user_id = str(uuid.uuid4())
        new_jti = "new-device-jti"
        old_jti = "old-device-jti"

        redis_client = MagicMock()
        redis_client.get.return_value = new_jti.encode()  # current JTI is new
        cache = RedisJwtRevocationCache(redis_client)

        import app.extensions.jwt_callbacks as _m

        with app.app_context():
            with patch.object(_m, "get_jwt_revocation_cache", return_value=cache):
                # old_jti is being validated — it's not the current one
                result = _m._is_access_token_revoked(user_id, old_jti)
                from flask import g as flask_g

                displaced = getattr(flask_g, "session_displaced", False)

        assert result is True
        assert displaced is True

    def test_session_displaced_not_set_when_jti_matches(self, app: Any) -> None:
        """Cache hit with the same JTI → valid token, no displacement."""
        user_id = str(uuid.uuid4())
        current_jti = "same-jti"

        redis_client = MagicMock()
        redis_client.get.return_value = current_jti.encode()
        cache = RedisJwtRevocationCache(redis_client)

        import app.extensions.jwt_callbacks as _m

        with app.app_context():
            with patch.object(_m, "get_jwt_revocation_cache", return_value=cache):
                result = _m._is_access_token_revoked(user_id, current_jti)
                from flask import g as flask_g

                displaced = getattr(flask_g, "session_displaced", False)

        assert result is False
        assert displaced is False

    def test_session_displaced_set_on_db_fallback_with_nonnull_current_jti(
        self, app: Any
    ) -> None:
        """Cache miss + DB shows non-null current_jti ≠ incoming → SESSION_DISPLACED."""
        user_id = str(uuid.uuid4())
        incoming_jti = "old-jti"

        noop_cache = _NoOpJwtRevocationCache()
        mock_user = MagicMock()
        mock_user.current_jti = "new-session-jti"  # a different session is active
        mock_user.deleted_at = None
        mock_user.blocked_at = None

        import app.extensions.jwt_callbacks as _m

        with app.app_context():
            with (
                patch.object(_m, "get_jwt_revocation_cache", return_value=noop_cache),
                patch.object(_m, "db") as mock_db,
                patch.object(_m, "UUID", side_effect=uuid.UUID),
            ):
                mock_db.session.get.return_value = mock_user
                result = _m._is_access_token_revoked(user_id, incoming_jti)
                from flask import g as flask_g

                displaced = getattr(flask_g, "session_displaced", False)

        assert result is True
        assert displaced is True

    def test_session_not_displaced_when_current_jti_is_null(self, app: Any) -> None:
        """Cache miss + DB shows null current_jti → explicit logout, not displaced."""
        user_id = str(uuid.uuid4())
        incoming_jti = "some-jti"

        noop_cache = _NoOpJwtRevocationCache()
        mock_user = MagicMock()
        mock_user.current_jti = None  # explicit logout cleared it
        mock_user.deleted_at = None
        mock_user.blocked_at = None

        import app.extensions.jwt_callbacks as _m

        with app.app_context():
            with (
                patch.object(_m, "get_jwt_revocation_cache", return_value=noop_cache),
                patch.object(_m, "db") as mock_db,
                patch.object(_m, "UUID", side_effect=uuid.UUID),
            ):
                mock_db.session.get.return_value = mock_user
                result = _m._is_access_token_revoked(user_id, incoming_jti)
                from flask import g as flask_g

                displaced = getattr(flask_g, "session_displaced", False)

        assert result is True
        assert displaced is False


# ---------------------------------------------------------------------------
# Integration tests — logout invalidates cache (via HTTP)
# ---------------------------------------------------------------------------


class TestLogoutCacheInvalidation:
    """Verifies that the logout endpoint invalidates the JWT revocation cache."""

    def _register_and_login(self, client: Any) -> tuple[str, str]:
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "name": f"cache-test-{suffix}",
            "email": f"cache-test-{suffix}@example.com",
            "password": "StrongPass@123",
        }
        reg = client.post("/auth/register", json=payload)
        assert reg.status_code == 201

        login = client.post(
            "/auth/login",
            headers={"X-API-Contract": "v2"},
            json={"email": payload["email"], "password": payload["password"]},
        )
        assert login.status_code == 200
        token = login.get_json()["data"]["token"]
        user_id = login.get_json()["data"]["user"]["id"]
        return token, user_id

    def test_logout_deletes_cache_key(self, client: Any, monkeypatch: Any) -> None:
        reset_jwt_revocation_cache_for_tests()
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("JWT_REVOCATION_REDIS_URL", raising=False)

        token, user_id = self._register_and_login(client)

        redis_client = MagicMock()
        redis_client.get.return_value = None
        fake_cache = RedisJwtRevocationCache(redis_client)

        with patch(
            "app.controllers.auth.logout_resource.get_jwt_revocation_cache",
            return_value=fake_cache,
        ):
            resp = client.post(
                "/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200

        redis_client.delete.assert_called_once_with(f"jwt:revoked:{user_id}")
