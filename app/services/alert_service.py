"""Alert dispatch service — J11-2 (alert trigger matrix + preference management)."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.extensions.database import db
from app.models.alert import Alert, AlertPreference, AlertStatus
from app.utils.datetime_utils import utc_now_naive

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Trigger matrix
# Maps alert category -> default metadata for dispatch decisions.
# ---------------------------------------------------------------------------

TRIGGER_MATRIX: dict[str, dict[str, str]] = {
    "balance_low": {"severity": "warning", "category": "wallet"},
    "goal_deadline": {"severity": "info", "category": "goals"},
    "suspicious_transaction": {"severity": "critical", "category": "transactions"},
    "subscription_expiring": {"severity": "warning", "category": "subscription"},
    "due_soon_7_days": {"severity": "info", "category": "due_soon"},
    "due_soon_1_day": {"severity": "warning", "category": "due_soon"},
}

# Browser-push copy per alert type: (title, body, click-through path).
_PUSH_COPY: dict[str, tuple[str, str, str]] = {
    "balance_low": (
        "Saldo baixo",
        "Seu saldo está baixo. Confira sua carteira.",
        "/dashboard",
    ),
    "goal_deadline": ("Meta chegando", "Uma meta está perto do prazo.", "/goals"),
    "suspicious_transaction": (
        "Transação suspeita",
        "Detectamos uma transação fora do padrão.",
        "/transactions",
    ),
    "subscription_expiring": (
        "Assinatura expirando",
        "Sua assinatura está perto de expirar.",
        "/subscription",
    ),
    "due_soon_7_days": (
        "Vencimento em 7 dias",
        "Você tem uma conta vencendo em breve.",
        "/transactions",
    ),
    "due_soon_1_day": (
        "Vence amanhã",
        "Você tem uma conta vencendo amanhã.",
        "/transactions",
    ),
}


def _dispatch_web_push(user_id: UUID, alert_type: str) -> None:
    """Best-effort browser push for a dispatched alert. Never raises."""
    copy = _PUSH_COPY.get(alert_type)
    if copy is None:
        return
    title, body, url = copy
    try:
        from app.services.web_push_service import send_web_push

        send_web_push(user_id, title=title, body=body, url=url, tag=alert_type)
    except Exception as exc:  # noqa: BLE001 — push must never break alert creation
        log.warning(
            "alert.web_push_failed user_id=%s type=%s error=%s",
            user_id,
            alert_type,
            exc,
        )


class AlertServiceError(Exception):
    """Domain error raised by alert service operations."""

    def __init__(
        self,
        message: str,
        code: str = "ALERT_ERROR",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


def _get_preference(user_id: UUID, category: str) -> AlertPreference | None:
    """Return the AlertPreference for (user, category), or None if absent."""
    from typing import cast

    result = AlertPreference.query.filter_by(user_id=user_id, category=category).first()
    return cast("AlertPreference | None", result)


def _is_dispatch_allowed(user_id: UUID, alert_type: str) -> bool:
    """Return True when the user's preference allows the alert to be created.

    Rules:
    - If no preference record exists, default is enabled (opt-in by default).
    - If the preference has global_opt_out=True, dispatch is blocked.
    - Otherwise the per-category `enabled` flag decides.
    """
    matrix_entry = TRIGGER_MATRIX.get(alert_type)
    if matrix_entry is None:
        return False  # unknown alert type — never dispatch

    category = matrix_entry["category"]
    pref = _get_preference(user_id, category)
    if pref is None:
        return True  # no explicit preference → opt-in by default
    if pref.global_opt_out:
        return False
    return bool(pref.enabled)


def dispatch_alert(
    user_id: UUID,
    alert_type: str,
    context: dict[str, Any] | None = None,
) -> Alert | None:
    """Create and persist an Alert for *user_id* if preferences allow it.

    Returns the created Alert, or None when dispatch was blocked by preference.
    Raises AlertServiceError for unknown alert types.
    """
    if alert_type not in TRIGGER_MATRIX:
        raise AlertServiceError(
            message=f"Unknown alert type: {alert_type!r}",
            code="UNKNOWN_ALERT_TYPE",
            status_code=400,
        )

    if not _is_dispatch_allowed(user_id, alert_type):
        return None

    matrix_entry = TRIGGER_MATRIX[alert_type]
    category = matrix_entry["category"]
    ctx = context or {}

    alert = Alert(
        user_id=user_id,
        category=category,
        status=AlertStatus.PENDING,
        entity_type=ctx.get("entity_type"),
        entity_id=ctx.get("entity_id"),
        triggered_at=utc_now_naive(),
    )
    db.session.add(alert)
    db.session.commit()
    _dispatch_web_push(user_id, alert_type)
    return alert


def get_user_alerts(
    user_id: UUID,
    *,
    unread_only: bool = False,
) -> list[Alert]:
    """Return alerts belonging to *user_id*, ordered by triggered_at desc.

    When *unread_only* is True, only alerts with status=PENDING are returned
    (PENDING represents unread/unsent in this model).
    """
    query = Alert.query.filter_by(user_id=user_id)
    if unread_only:
        query = query.filter(Alert.status == AlertStatus.PENDING)
    return list(query.order_by(Alert.triggered_at.desc()).all())


def mark_read(alert_id: UUID, user_id: UUID) -> Alert:
    """Mark the alert as SENT (read) and record sent_at timestamp.

    Raises AlertServiceError when the alert is not found or belongs to another user.
    """
    alert: Alert | None = Alert.query.filter_by(id=alert_id).first()
    if alert is None:
        raise AlertServiceError(
            message="Alerta não encontrado.",
            code="NOT_FOUND",
            status_code=404,
        )
    if str(alert.user_id) != str(user_id):
        raise AlertServiceError(
            message="Você não tem permissão para acessar este alerta.",
            code="FORBIDDEN",
            status_code=403,
        )
    alert.status = AlertStatus.SENT
    alert.sent_at = utc_now_naive()
    db.session.commit()
    return alert


def delete_alert(alert_id: UUID, user_id: UUID) -> None:
    """Delete an alert belonging to *user_id*.

    Raises AlertServiceError when not found or owned by another user.
    """
    alert: Alert | None = Alert.query.filter_by(id=alert_id).first()
    if alert is None:
        raise AlertServiceError(
            message="Alerta não encontrado.",
            code="NOT_FOUND",
            status_code=404,
        )
    if str(alert.user_id) != str(user_id):
        raise AlertServiceError(
            message="Você não tem permissão para remover este alerta.",
            code="FORBIDDEN",
            status_code=403,
        )
    db.session.delete(alert)
    db.session.commit()


def get_preferences(user_id: UUID) -> list[AlertPreference]:
    """Return all AlertPreference records for *user_id*."""
    return list(
        AlertPreference.query.filter_by(user_id=user_id)
        .order_by(AlertPreference.category.asc())
        .all()
    )


def upsert_preference(
    user_id: UUID,
    category: str,
    *,
    enabled: bool,
    channels: list[str] | None = None,
    global_opt_out: bool = False,
) -> AlertPreference:
    """Create or update an AlertPreference for (user_id, category).

    ``channels`` is accepted for forward-compatibility (multi-channel routing
    is on the roadmap) but currently ignored — the model has no column for it
    yet. Discarded explicitly to keep linters quiet without losing the public
    signature.

    Returns the persisted AlertPreference.
    """
    del channels
    pref: AlertPreference | None = _get_preference(user_id, category)
    if pref is None:
        pref = AlertPreference(
            user_id=user_id,
            category=category,
            enabled=enabled,
            global_opt_out=global_opt_out,
        )
        db.session.add(pref)
    else:
        pref.enabled = enabled
        pref.global_opt_out = global_opt_out
    db.session.commit()
    return pref
