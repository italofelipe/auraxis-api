# mypy: disable-error-code=name-defined

from __future__ import annotations

import enum
from uuid import uuid4

from sqlalchemy.dialects.postgresql import UUID

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive


def _enum_values(e: type[enum.Enum]) -> list[str]:
    return [m.value for m in e]


class InsightType(enum.Enum):
    """Type of AI insight generated for a user."""

    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    recap = "recap"  # end-of-month comprehensive analysis
    spending_patterns = "spending_patterns"  # cached "Radar de Gastos" (cron-generated)


class AIInsight(db.Model):
    """First-class record of an AI-generated financial insight.

    Each insight is tied to a user, a calendar period, and an optional
    reference to the previous insight so the LLM can maintain context
    across consecutive generations.

    Unlike LLMAuditLog (write-only cost/token tracking), this model is
    designed for retrieval: users can browse their insight history, and
    the advisory service reads the latest entry before generating the next.
    """

    __tablename__ = "ai_insights"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    content = db.Column(db.Text, nullable=False)
    insight_type = db.Column(
        db.Enum(
            InsightType,
            name="insight_type_enum",
            native_enum=False,
            values_callable=_enum_values,
        ),
        nullable=False,
    )
    # Human-readable period key for deduplication and display.
    # daily             → "YYYY-MM-DD"
    # weekly            → "YYYY-WNN"  (ISO week, e.g. "2026-W20")
    # monthly           → "YYYY-MM"
    # recap             → "YYYY-MM-recap"
    # spending_patterns → "YYYY-MM-DD"
    period_label = db.Column(db.String(30), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    model = db.Column(db.String(80), nullable=False)
    tokens_used = db.Column(db.Integer, nullable=False, default=0)
    cost_usd = db.Column(db.Numeric(10, 8), nullable=False, default=0)
    # Self-referential FK: chains today's insight to yesterday's, giving the
    # LLM context about what changed since the last generation.
    previous_insight_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("ai_insights.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime, default=utc_now_naive, nullable=False)
    # Snapshot/audit metadata for observability — populated since MVP-3
    # (Sprint 5 obs-1). Legacy rows have NULL. Stored as JSON in Text for
    # SQLite parity with PG; access via `metadata_dict` property.
    metadata_json = db.Column(db.Text, nullable=True)

    @property
    def metadata_dict(self) -> dict[str, object]:
        """Decode `metadata_json` to a dict, or {} when missing/invalid."""
        import json as _json

        if not self.metadata_json:
            return {}
        try:
            decoded = _json.loads(self.metadata_json)
        except (ValueError, TypeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @metadata_dict.setter
    def metadata_dict(self, value: dict[str, object] | None) -> None:
        import json as _json

        if value is None:
            self.metadata_json = None
        else:
            self.metadata_json = _json.dumps(value, ensure_ascii=False, sort_keys=True)

    __table_args__ = (
        db.Index("ix_ai_insights_user_id", "user_id"),
        db.Index("ix_ai_insights_user_created", "user_id", "created_at"),
        db.Index(
            "ix_ai_insights_user_type_period",
            "user_id",
            "insight_type",
            "period_label",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AIInsight id={self.id} user_id={self.user_id} "
            f"type={self.insight_type.value!r} period={self.period_label!r}>"
        )
