"""Web Push (VAPID) dispatch service (#1446).

Sends browser push notifications to a user's registered ``web_push``
subscriptions using the VAPID protocol (pywebpush). It is a no-op when VAPID
keys are not configured, so the application runs normally without push enabled.

Companion to ``analysis_ready_notification_service`` (Expo/mobile push); this
module owns the browser/PWA channel.
"""

from __future__ import annotations

import json
import logging
from typing import cast
from uuid import UUID

from flask import current_app
from pywebpush import WebPushException, webpush

from app.extensions.database import db
from app.models.push_subscription import PushSubscription, PushTransport

log = logging.getLogger(__name__)

# Push endpoints answer 404/410 once the browser subscription is gone — prune
# those so a dead device never blocks future sends.
_GONE_STATUSES = frozenset({404, 410})
_MAX_BODY_CHARS = 240


def _status_of(exc: WebPushException) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


def send_web_push(
    user_id: UUID,
    *,
    title: str,
    body: str,
    url: str = "/dashboard",
    tag: str = "auraxis",
) -> int:
    """Send a Web Push notification to every web_push subscription of *user_id*.

    No-op (returns 0) when VAPID is not configured. Individual delivery
    failures are swallowed so one dead endpoint never blocks the rest; gone
    subscriptions (404/410) are deleted.

    Args:
        user_id: Recipient user.
        title: Notification title.
        body: Notification body (truncated to a safe length).
        url: Relative path opened when the user clicks the notification.
        tag: Notification tag used to coalesce duplicates.

    Returns:
        Number of subscriptions the push was accepted by.
    """
    private_key = str(current_app.config.get("VAPID_PRIVATE_KEY") or "")
    public_key = str(current_app.config.get("VAPID_PUBLIC_KEY") or "")
    if not private_key or not public_key:
        log.debug("web_push.skipped reason=vapid_not_configured user_id=%s", user_id)
        return 0

    subject = str(
        current_app.config.get("VAPID_SUBJECT") or "mailto:suporte@auraxis.com.br"
    )
    subscriptions = cast(
        "list[PushSubscription]",
        PushSubscription.query.filter_by(
            user_id=user_id,
            transport=PushTransport.web_push,
        ).all(),
    )
    if not subscriptions:
        return 0

    payload = json.dumps(
        {"title": title, "body": body[:_MAX_BODY_CHARS], "url": url, "tag": tag}
    )
    sent = 0
    stale: list[PushSubscription] = []
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": str(sub.endpoint),
                    "keys": dict(sub.keys or {}),
                },
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": subject},
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            status = _status_of(exc)
            if status in _GONE_STATUSES:
                stale.append(sub)
                log.info(
                    "web_push.subscription_gone user_id=%s status=%s", user_id, status
                )
            else:
                log.warning(
                    "web_push.failed user_id=%s status=%s error=%s",
                    user_id,
                    status,
                    str(exc)[:120],
                )
        except Exception as exc:  # noqa: BLE001 — never let push break the caller
            log.warning("web_push.error user_id=%s error=%s", user_id, exc)

    if stale:
        for sub in stale:
            db.session.delete(sub)
        db.session.commit()

    return sent


__all__ = ["send_web_push"]
