"""Notification service for 'AI analysis ready' events (#1207).

Dispatches an email (and optionally a push notification) to a premium user
when a new AI financial analysis is available for them to view.

Usage::

    from app.services.analysis_ready_notification_service import (
        dispatch_analysis_ready_notification,
    )

    result = dispatch_analysis_ready_notification(
        user_id=uuid,
        summary_preview="Seus gastos com alimentação subiram 18% este mês...",
    )
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import requests as http_client

from app.extensions.database import db
from app.models.push_subscription import PushSubscription, PushTransport
from app.models.user import User
from app.services.email_provider import EmailMessage, get_default_email_provider
from app.services.email_templates.base import (
    render_analysis_ready_email,
    web_base_url,
)
from app.services.email_templates.insight_content import insight_email_content
from app.services.entitlement_service import has_entitlement

log = logging.getLogger(__name__)

_EMAIL_REMINDERS_FEATURE = "email_reminders"
_DEFAULT_SUMMARY = (
    "Sua análise financeira semanal está disponível. "
    "Acesse o dashboard para ver seus insights personalizados."
)
_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


@dataclass(frozen=True)
class AnalysisNotificationResult:
    email_sent: bool
    push_sent: bool
    skipped_reason: str | None = None


def dispatch_analysis_ready_notification(
    *,
    user_id: UUID,
    summary_preview: str = _DEFAULT_SUMMARY,
    insight_id: UUID | str | None = None,
    insight_payload: Mapping[str, Any] | None = None,
) -> AnalysisNotificationResult:
    """Send 'analysis ready' notification to a premium user.

    Sends an email when the user has the ``email_reminders`` entitlement.
    Skips silently for free-tier users.

    Args:
        user_id: The user to notify.
        summary_preview: A 1-2 sentence AI-generated preview included in the email.
        insight_id: Deep-links the CTA straight to this insight.
        insight_payload: The full insight generation result — its items are
            embedded in the email body (#1617). Malformed payloads simply
            yield no embedded section.

    Returns:
        AnalysisNotificationResult with flags indicating what was sent.
    """
    if not has_entitlement(user_id, _EMAIL_REMINDERS_FEATURE):
        log.debug(
            "analysis_ready_notification.skipped user_id=%s reason=no_entitlement",
            user_id,
        )
        return AnalysisNotificationResult(
            email_sent=False,
            push_sent=False,
            skipped_reason="no_entitlement",
        )

    user = db.session.get(User, user_id)
    if user is None:
        log.warning(
            "analysis_ready_notification.skipped user_id=%s reason=user_not_found",
            user_id,
        )
        return AnalysisNotificationResult(
            email_sent=False,
            push_sent=False,
            skipped_reason="user_not_found",
        )

    first_name = _extract_first_name(user)
    insight_url = (
        f"{web_base_url()}/insights?open={insight_id}"
        if insight_id
        else f"{web_base_url()}/insights"
    )
    content = insight_email_content(insight_payload)
    email_sent = _send_email(
        to_email=str(user.email),
        first_name=first_name,
        summary_preview=summary_preview,
        insight_url=insight_url,
        items=content.items,
        suggestion=content.suggestion,
    )
    push_sent = _send_expo_push(
        user_id=user_id,
        first_name=first_name,
        summary_preview=summary_preview,
    )

    return AnalysisNotificationResult(
        email_sent=email_sent,
        push_sent=push_sent,
    )


def _extract_first_name(user: User) -> str:
    name = getattr(user, "name", None) or getattr(user, "full_name", None) or ""
    return str(name).split()[0] if name else "você"


def _send_email(
    *,
    to_email: str,
    first_name: str,
    summary_preview: str,
    insight_url: str | None = None,
    items: list[tuple[str, str]] | None = None,
    suggestion: str = "",
) -> bool:
    """Send the analysis-ready email. Returns True on success, False on failure."""
    try:
        html, text = render_analysis_ready_email(
            first_name=first_name,
            summary_preview=summary_preview,
            insight_url=insight_url,
            items=items,
            suggestion=suggestion,
        )
        provider = get_default_email_provider()
        provider.send(
            EmailMessage(
                to_email=to_email,
                subject=f"Sua análise financeira está pronta, {first_name}!",
                html=html,
                text=text,
                tag="analysis_ready",
            )
        )
        log.info(
            "analysis_ready_notification.email_sent to=%s",
            to_email,
        )
        return True
    except Exception as exc:
        log.warning(
            "analysis_ready_notification.email_failed to=%s error=%s",
            to_email,
            exc,
        )
        return False


def _send_expo_push(
    *,
    user_id: UUID,
    first_name: str,
    summary_preview: str,
) -> bool:
    """Send Expo push notifications to all registered Expo tokens for the user.

    Returns True if at least one notification was dispatched successfully.
    Swallows individual token failures so one bad token doesn't block the rest.
    """
    subscriptions = cast(
        list[PushSubscription],
        PushSubscription.query.filter_by(
            user_id=user_id,
            transport=PushTransport.expo,
        ).all(),
    )
    if not subscriptions:
        return False

    any_sent = False
    for sub in subscriptions:
        token = str(sub.endpoint)
        if not token.startswith("ExponentPushToken["):
            continue
        try:
            resp = http_client.post(
                _EXPO_PUSH_URL,
                json={
                    "to": token,
                    "title": f"Análise pronta, {first_name}!",
                    "body": summary_preview[:200],
                    "data": {"screen": "Dashboard"},
                    "sound": "default",
                    "channelId": "analysis_ready",
                },
                timeout=10,
            )
            if resp.ok:
                any_sent = True
                log.info(
                    "analysis_ready_notification.push_sent user_id=%s token=%s...",
                    user_id,
                    token[:30],
                )
            else:
                log.warning(
                    "analysis_ready_notification.push_rejected user_id=%s status=%s",
                    user_id,
                    resp.status_code,
                )
        except Exception as exc:
            log.warning(
                "analysis_ready_notification.push_failed user_id=%s error=%s",
                user_id,
                exc,
            )
    return any_sent


__all__ = [
    "AnalysisNotificationResult",
    "dispatch_analysis_ready_notification",
]
