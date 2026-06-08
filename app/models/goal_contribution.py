# mypy: disable-error-code=name-defined

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.dialects.postgresql import UUID

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive


class GoalContribution(db.Model):
    """Records each monetary change to a Goal's current_amount.

    Created automatically as a side-effect of update_goal() whenever
    current_amount changes, giving the AI advisory service a reliable
    contribution history for cross-domain insight generation.

    amount is the signed delta (positive = deposit, negative = reversal).
    """

    __tablename__ = "goal_contributions"

    id = db.Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    goal_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("goals.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    note = db.Column(db.String(200), nullable=True)
    # User-facing contribution date (may be back-dated by the client). Defaults
    # to the creation date. created_at stays as the immutable audit timestamp.
    occurred_at = db.Column(
        db.Date, default=lambda: utc_now_naive().date(), nullable=False
    )
    created_at = db.Column(db.DateTime, default=utc_now_naive, nullable=False)

    __table_args__ = (
        db.Index("ix_goal_contributions_user_goal", "user_id", "goal_id"),
        db.Index("ix_goal_contributions_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<GoalContribution id={self.id} goal_id={self.goal_id} "
            f"amount={self.amount}>"
        )
