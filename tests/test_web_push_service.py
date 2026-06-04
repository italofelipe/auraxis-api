"""Tests for the Web Push (VAPID) dispatch service (#1446)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pywebpush import WebPushException

from app.extensions.database import db
from app.models.push_subscription import PushSubscription, PushTransport
from app.services import web_push_service


def _web_sub(
    user_id, endpoint: str = "https://fcm.googleapis.com/x"
) -> PushSubscription:
    return PushSubscription(
        user_id=user_id,
        transport=PushTransport.web_push,
        endpoint=endpoint,
        keys={"p256dh": "p", "auth": "a"},
    )


def _configure_vapid(app: object) -> None:
    app.config["VAPID_PUBLIC_KEY"] = "pub"  # type: ignore[attr-defined]
    app.config["VAPID_PRIVATE_KEY"] = "priv"  # type: ignore[attr-defined]
    app.config["VAPID_SUBJECT"] = "mailto:suporte@auraxis.com.br"  # type: ignore[attr-defined]


def test_noop_when_vapid_not_configured(
    app: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():  # type: ignore[attr-defined]
        app.config["VAPID_PUBLIC_KEY"] = ""  # type: ignore[attr-defined]
        app.config["VAPID_PRIVATE_KEY"] = ""  # type: ignore[attr-defined]
        user_id = uuid4()
        db.session.add(_web_sub(user_id))
        db.session.commit()

        called = {"n": 0}
        monkeypatch.setattr(
            web_push_service,
            "webpush",
            lambda **_: called.__setitem__("n", called["n"] + 1),
        )

        assert web_push_service.send_web_push(user_id, title="t", body="b") == 0
        assert called["n"] == 0


def test_sends_to_each_web_push_subscription(
    app: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():  # type: ignore[attr-defined]
        _configure_vapid(app)
        user_id = uuid4()
        db.session.add_all(
            [_web_sub(user_id, "https://a"), _web_sub(user_id, "https://b")]
        )
        # An Expo subscription must be ignored by the web-push channel.
        db.session.add(
            PushSubscription(
                user_id=user_id,
                transport=PushTransport.expo,
                endpoint="ExponentPushToken[x]",
            )
        )
        db.session.commit()

        seen: list[str] = []
        monkeypatch.setattr(
            web_push_service,
            "webpush",
            lambda **kwargs: seen.append(kwargs["subscription_info"]["endpoint"]),
        )

        sent = web_push_service.send_web_push(
            user_id, title="Vence amanhã", body="conta", url="/transactions"
        )

        assert sent == 2
        assert sorted(seen) == ["https://a", "https://b"]


def test_prunes_gone_subscriptions(
    app: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():  # type: ignore[attr-defined]
        _configure_vapid(app)
        user_id = uuid4()
        db.session.add(_web_sub(user_id, "https://gone"))
        db.session.commit()

        def _raise_gone(**_: object) -> None:
            raise WebPushException("gone", response=SimpleNamespace(status_code=410))

        monkeypatch.setattr(web_push_service, "webpush", _raise_gone)

        sent = web_push_service.send_web_push(user_id, title="t", body="b")

        assert sent == 0
        remaining = PushSubscription.query.filter_by(user_id=user_id).count()
        assert remaining == 0  # the 410 endpoint was pruned


def test_dispatch_alert_triggers_web_push(
    app: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import alert_service

    with app.app_context():  # type: ignore[attr-defined]
        user_id = uuid4()
        calls: list[tuple] = []
        monkeypatch.setattr(
            "app.services.web_push_service.send_web_push",
            lambda uid, **kw: calls.append((uid, kw.get("title"), kw.get("url"))) or 1,
        )

        alert_service.dispatch_alert(user_id, "due_soon_1_day")

        assert len(calls) == 1
        assert calls[0][0] == user_id
        assert calls[0][2] == "/transactions"
