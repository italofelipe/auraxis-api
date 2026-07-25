# mypy: disable-error-code="name-defined"
"""Alert and AlertPreference models — J11 (alert system)."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy.dialects.postgresql import UUID

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive


class AlertStatus(enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """SQLAlchemy ``values_callable``: persist ``Enum.value`` (lowercase) and not
    ``Enum.name`` (uppercase). The ``alertstatus`` Postgres enum (migration
    ``j618``) only declares lowercase labels, so without this every Alert INSERT
    sends ``"SENT"`` and Postgres raises InvalidTextRepresentation — the root
    cause of the reminder-job failures (#989).
    """
    return [str(member.value) for member in enum_cls]


class Alert(db.Model):
    """A single alert dispatch record for a user."""

    __tablename__ = "alerts"

    id = db.Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    # Valid values: due_soon | overdue | onboarding_pending | monthly_summary
    category = db.Column(db.String(40), nullable=False)
    status = db.Column(
        db.Enum(AlertStatus, values_callable=_enum_values),
        nullable=False,
        default=AlertStatus.PENDING,
    )
    entity_type = db.Column(db.String(40), nullable=True)
    entity_id = db.Column(UUID(as_uuid=True), nullable=True)
    triggered_at = db.Column(db.DateTime, nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now_naive)

    __table_args__ = (
        db.Index(
            "ix_alerts_user_category_triggered",
            "user_id",
            "category",
            "triggered_at",
        ),
        db.Index("ix_alerts_user_sent_at", "user_id", "sent_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Alert user={self.user_id} category={self.category} status={self.status}>"
        )


class AlertPreference(db.Model):
    """Per-user, per-category alert opt-in/out configuration."""

    __tablename__ = "alert_preferences"

    id = db.Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    # When true, disables ALL alerts regardless of per-category `enabled`
    global_opt_out = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "category", name="uq_alert_preferences_user_category"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AlertPreference user={self.user_id} category={self.category}"
            f" enabled={self.enabled}>"
        )
