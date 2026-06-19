# mypy: disable-error-code=name-defined

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy.dialects.postgresql import UUID

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive

CREDIT_CARD_BRAND_VALUES = ("visa", "mastercard", "elo", "hipercard", "amex", "other")


class CreditCard(db.Model):
    __tablename__ = "credit_cards"
    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = db.Column(UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(20), nullable=True)
    limit_amount = db.Column(db.Numeric(12, 2), nullable=True)
    closing_day = db.Column(db.Integer, nullable=True)
    due_day = db.Column(db.Integer, nullable=True)
    bank = db.Column(db.String(80), nullable=True)
    description = db.Column(db.String(300), nullable=True)
    # Stored as JSON-encoded list of strings (cap 12 × 120 chars). Text rather
    # than PG ARRAY to keep SQLite test parity.
    benefits = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
        nullable=False,
    )

    @property
    def benefits_list(self) -> list[str]:
        """Decode the JSON-encoded `benefits` text column into a Python list."""
        if not self.benefits:
            return []
        try:
            decoded = json.loads(self.benefits)
        except (ValueError, TypeError):
            return []
        return [str(item) for item in decoded] if isinstance(decoded, list) else []

    @benefits_list.setter
    def benefits_list(self, value: list[str] | None) -> None:
        if value is None:
            self.benefits = None
        else:
            self.benefits = json.dumps(list(value), ensure_ascii=False)
