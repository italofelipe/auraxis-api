"""Tests for multi-device session management endpoints (#1028).

Covers:
- GET  /auth/sessions — list active sessions (auth gate + happy path)
- DELETE /auth/sessions/<id> — revoke specific session
- DELETE /auth/sessions — revoke all sessions (global logout)
- Session service: create, rotate, revoke, list, reuse detection
"""

from __future__ import annotations

import uuid

import pytest

from app.application.services.session_service import (
    SessionNotFoundError,
    TokenReuseError,
    create_session,
    is_access_jti_active,
    revoke_all_sessions,
    revoke_session,
    rotate_session_by_jti,
)
from app.models.refresh_token import RefreshToken
from tests.helpers import auth_header as _auth
from tests.helpers import register_and_login_with_refresh as _register_and_login

# ---------------------------------------------------------------------------
# Auth gates
# ---------------------------------------------------------------------------


class TestSessionAuthGates:
    def test_list_sessions_unauthenticated(self, client) -> None:
        resp = client.get("/auth/sessions")
        assert resp.status_code == 401

    def test_revoke_all_unauthenticated(self, client) -> None:
        resp = client.delete("/auth/sessions")
        assert resp.status_code == 401

    def test_revoke_specific_unauthenticated(self, client) -> None:
        resp = client.delete(f"/auth/sessions/{uuid.uuid4()}")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /auth/sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_returns_200(self, client) -> None:
        token, _ = _register_and_login(client, "sess-list")
        resp = client.get("/auth/sessions", headers=_auth(token))
        assert resp.status_code == 200

    def test_response_has_sessions_key(self, client) -> None:
        token, _ = _register_and_login(client, "sess-keys")
        resp = client.get("/auth/sessions", headers=_auth(token))
        body = resp.get_json()
        data = body.get("data") or body
        assert "sessions" in data

    def test_sessions_is_list(self, client) -> None:
        token, _ = _register_and_login(client, "sess-type")
        resp = client.get("/auth/sessions", headers=_auth(token))
        data = resp.get_json().get("data") or resp.get_json()
        assert isinstance(data["sessions"], list)

    def test_login_creates_session(self, client) -> None:
        token, _ = _register_and_login(client, "sess-create")
        resp = client.get("/auth/sessions", headers=_auth(token))
        data = resp.get_json().get("data") or resp.get_json()
        assert len(data["sessions"]) >= 1

    def test_session_has_required_fields(self, client) -> None:
        token, _ = _register_and_login(client, "sess-shape")
        resp = client.get("/auth/sessions", headers=_auth(token))
        data = resp.get_json().get("data") or resp.get_json()
        for s in data["sessions"]:
            assert "id" in s
            assert "device_info" in s
            assert "created_at" in s
            assert "expires_at" in s
            assert "is_current" in s

    def test_current_session_marked(self, client) -> None:
        token, _ = _register_and_login(client, "sess-current")
        resp = client.get("/auth/sessions", headers=_auth(token))
        data = resp.get_json().get("data") or resp.get_json()
        current_sessions = [s for s in data["sessions"] if s["is_current"]]
        assert len(current_sessions) == 1


# ---------------------------------------------------------------------------
# DELETE /auth/sessions (global logout)
# ---------------------------------------------------------------------------


class TestRevokeAllSessions:
    def test_returns_200(self, client) -> None:
        token, _ = _register_and_login(client, "sess-revall")
        resp = client.delete("/auth/sessions", headers=_auth(token))
        assert resp.status_code == 200

    def test_response_has_revoked_count(self, client) -> None:
        token, _ = _register_and_login(client, "sess-revcount")
        resp = client.delete("/auth/sessions", headers=_auth(token))
        data = resp.get_json().get("data") or resp.get_json()
        assert "revoked" in data

    def test_access_token_revoked_after_revoke_all(self, client) -> None:
        """After revoking all sessions the current access token is also invalid."""
        token, _ = _register_and_login(client, "sess-empty")
        resp = client.delete("/auth/sessions", headers=_auth(token))
        assert resp.status_code == 200
        # Old access token no longer works — all RefreshToken rows revoked.
        resp2 = client.get("/auth/sessions", headers=_auth(token))
        assert resp2.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /auth/sessions/<id>
# ---------------------------------------------------------------------------


class TestRevokeSession:
    def test_revoke_specific_session_returns_200(self, client) -> None:
        token, _ = _register_and_login(client, "sess-rev1")
        list_resp = client.get("/auth/sessions", headers=_auth(token))
        data = list_resp.get_json().get("data") or list_resp.get_json()
        session_id = data["sessions"][0]["id"]
        resp = client.delete(f"/auth/sessions/{session_id}", headers=_auth(token))
        assert resp.status_code == 200

    def test_revoke_nonexistent_session_returns_404(self, client) -> None:
        token, _ = _register_and_login(client, "sess-rev404")
        resp = client.delete(f"/auth/sessions/{uuid.uuid4()}", headers=_auth(token))
        assert resp.status_code == 404

    def test_revoke_other_users_session_returns_404(self, app, client) -> None:
        token_a, _ = _register_and_login(client, "sess-revA")
        token_b, _ = _register_and_login(client, "sess-revB")
        list_resp = client.get("/auth/sessions", headers=_auth(token_b))
        data = list_resp.get_json().get("data") or list_resp.get_json()
        session_b_id = data["sessions"][0]["id"]
        resp = client.delete(f"/auth/sessions/{session_b_id}", headers=_auth(token_a))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Session service unit tests
# ---------------------------------------------------------------------------


class TestSessionServiceCreate:
    def test_create_session_returns_refresh_token(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            rt = create_session(
                user_id=user_id,
                raw_refresh_token="raw-token",
                refresh_jti="jti-1",
                access_jti="acc-jti-1",
                user_agent="TestAgent/1.0",
                remote_addr="1.2.3.4",
            )
            assert rt.user_id == user_id
            assert rt.jti == "jti-1"
            assert rt.current_access_jti == "acc-jti-1"
            assert rt.revoked_at is None


class TestSessionServiceRotate:
    def test_rotate_by_jti_creates_new_session(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            create_session(
                user_id=user_id,
                raw_refresh_token="raw-tok",
                refresh_jti="old-jti",
                access_jti="old-acc",
            )
            new_rt = rotate_session_by_jti(
                old_jti="old-jti",
                new_raw_refresh_token="new-raw",
                new_refresh_jti="new-jti",
                new_access_jti="new-acc",
            )
            assert new_rt is not None
            assert new_rt.jti == "new-jti"
            old = RefreshToken.query.filter_by(jti="old-jti").first()
            assert old is not None and old.revoked_at is not None

    def test_rotate_revoked_jti_raises_token_reuse_error(self, app) -> None:
        """Reuse OUTSIDE the grace window is treated as theft → family revoked."""
        with app.app_context():
            from datetime import timedelta

            from app.application.services import session_service
            from app.extensions.database import db
            from app.utils.datetime_utils import utc_now_naive

            user_id = uuid.uuid4()
            rt = create_session(
                user_id=user_id,
                raw_refresh_token="raw-tok2",
                refresh_jti="reuse-jti",
                access_jti="reuse-acc",
            )
            # Revoked well outside the grace window → genuine replay, not a
            # concurrent boot refresh.
            rt.revoked_at = utc_now_naive() - timedelta(
                seconds=session_service._REUSE_GRACE_SECONDS + 60
            )
            db.session.commit()
            with pytest.raises(TokenReuseError):
                rotate_session_by_jti(
                    old_jti="reuse-jti",
                    new_raw_refresh_token="any",
                    new_refresh_jti="any-new",
                    new_access_jti="any-acc",
                )

    def test_rotate_within_grace_raises_concurrent_and_keeps_family(self, app) -> None:
        """A just-rotated token re-presented within the grace window is a benign
        concurrent refresh: ConcurrentRefreshError, family NOT revoked."""
        with app.app_context():
            from app.application.services.session_service import (
                ConcurrentRefreshError,
            )
            from app.extensions.database import db

            user_id = uuid.uuid4()
            create_session(
                user_id=user_id,
                raw_refresh_token="raw-grace",
                refresh_jti="grace-jti",
                access_jti="grace-acc",
            )
            # Winner rotates the token (revokes it ~now) and creates a successor.
            winner = rotate_session_by_jti(
                old_jti="grace-jti",
                new_raw_refresh_token="winner-raw",
                new_refresh_jti="winner-jti",
                new_access_jti="winner-acc",
            )
            db.session.commit()
            assert winner is not None
            family_id = winner.family_id

            # Loser presents the same (now just-revoked) jti within the grace window.
            with pytest.raises(ConcurrentRefreshError):
                rotate_session_by_jti(
                    old_jti="grace-jti",
                    new_raw_refresh_token="loser-raw",
                    new_refresh_jti="loser-jti",
                    new_access_jti="loser-acc",
                )

            # The winning successor must still be active — family NOT nuked.
            successor = RefreshToken.query.filter_by(jti="winner-jti").first()
            assert successor is not None
            assert successor.revoked_at is None
            active = (
                RefreshToken.query.filter_by(family_id=family_id)
                .filter(RefreshToken.revoked_at.is_(None))
                .count()
            )
            assert active == 1

    def test_rotate_unknown_jti_returns_none(self, app) -> None:
        with app.app_context():
            result = rotate_session_by_jti(
                old_jti="nonexistent-jti",
                new_raw_refresh_token="any",
                new_refresh_jti="any",
                new_access_jti="any",
            )
            assert result is None


class TestSessionServiceRevoke:
    def test_revoke_session_raises_for_wrong_user(self, app) -> None:
        with app.app_context():
            user_a = uuid.uuid4()
            user_b = uuid.uuid4()
            rt = create_session(
                user_id=user_a,
                raw_refresh_token="tok-a",
                refresh_jti="jti-a",
                access_jti="acc-a",
            )
            from app.extensions.database import db

            db.session.commit()
            with pytest.raises(SessionNotFoundError):
                revoke_session(session_id=rt.id, user_id=user_b)

    def test_revoke_all_returns_count(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            for i in range(3):
                create_session(
                    user_id=user_id,
                    raw_refresh_token=f"tok-{i}",
                    refresh_jti=f"jti-{i}",
                    access_jti=f"acc-{i}",
                )
            from app.extensions.database import db

            db.session.commit()
            count = revoke_all_sessions(user_id=user_id)
            assert count == 3


class TestSessionServiceIsAccessJtiActive:
    def test_active_jti_returns_true(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            create_session(
                user_id=user_id,
                raw_refresh_token="tok-active",
                refresh_jti="jti-active",
                access_jti="acc-active",
            )
            from app.extensions.database import db

            db.session.commit()
            assert is_access_jti_active(user_id=user_id, jti="acc-active") is True

    def test_unknown_jti_returns_false(self, app) -> None:
        with app.app_context():
            user_id = uuid.uuid4()
            assert is_access_jti_active(user_id=user_id, jti="no-such-jti") is False
