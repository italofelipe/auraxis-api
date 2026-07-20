# mypy: disable-error-code="name-defined"
"""Manual premium access override, independent from billing state."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import UUID

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive


class PremiumOverride(db.Model):
    __tablename__ = "premium_overrides"

    id = db.Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    granted_at = db.Column(db.DateTime, nullable=False, default=utc_now_naive)
    expires_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    reason = db.Column(db.Text, nullable=False)
    granted_by = db.Column(db.String(128), nullable=False)
    revoked_reason = db.Column(db.Text, nullable=True)
    revoked_by = db.Column(db.String(128), nullable=True)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=utc_now_naive,
        onupdate=utc_now_naive,
    )

    def is_active_at(self, now: datetime | None = None) -> bool:
        reference = now or utc_now_naive()
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > reference
        )


__all__ = ["PremiumOverride"]
