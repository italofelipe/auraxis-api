from __future__ import annotations

from datetime import date
from typing import Any

from marshmallow import (
    Schema,
    ValidationError,
    fields,
    pre_load,
    validate,
    validates,
)

from app.schemas.sanitization import sanitize_string_fields

GOAL_STATUSES = ("active", "completed", "paused", "cancelled")


class GoalSchema(Schema):
    class Meta:
        name = "Goal"

    id = fields.UUID(dump_only=True)
    user_id = fields.UUID(dump_only=True)
    title = fields.Str(required=True, validate=validate.Length(min=1, max=128))
    description = fields.Str(validate=validate.Length(max=500))
    category = fields.Str(validate=validate.Length(max=64))
    target_amount = fields.Decimal(
        as_string=True,
        required=True,
        validate=validate.Range(min=0.01),
    )
    current_amount = fields.Decimal(
        as_string=True,
        load_default="0.00",
        validate=validate.Range(min=0),
    )
    priority = fields.Int(load_default=3, validate=validate.Range(min=1, max=5))
    target_date = fields.Date(allow_none=True)
    status = fields.Str(
        load_default="active",
        validate=validate.OneOf(GOAL_STATUSES),
    )
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    @pre_load
    def sanitize_input(self, data: object, **kwargs: object) -> object:
        sanitized = sanitize_string_fields(
            data,
            {"title", "description", "category", "status"},
        )
        if isinstance(sanitized, dict) and isinstance(sanitized.get("status"), str):
            sanitized["status"] = str(sanitized["status"]).lower()
        return sanitized


class GoalContributionInputSchema(Schema):
    """Payload for registering a goal contribution (deposit or withdrawal).

    ``amount`` is a signed delta: positive deposits add to the goal, negative
    withdrawals subtract. Zero is rejected. ``occurred_at`` defaults to today
    and may be back-dated but never set in the future.
    """

    class Meta:
        name = "GoalContributionInput"

    amount = fields.Decimal(as_string=True, required=True)
    occurred_at = fields.Date(load_default=None, allow_none=True)
    note = fields.Str(allow_none=True, validate=validate.Length(max=200))

    @validates("amount")
    def _validate_amount(self, value: Any, **kwargs: Any) -> None:
        if value == 0:
            raise ValidationError("O valor do aporte/retirada não pode ser zero.")

    @validates("occurred_at")
    def _validate_occurred_at(self, value: date | None, **kwargs: Any) -> None:
        if value is not None and value > date.today():
            raise ValidationError("A data não pode ser futura.")

    @pre_load
    def sanitize_input(self, data: object, **kwargs: object) -> object:
        return sanitize_string_fields(data, {"note"})


class GoalContributionSchema(Schema):
    """Serialized goal contribution (audit history entry)."""

    class Meta:
        name = "GoalContribution"

    id = fields.UUID(dump_only=True)
    goal_id = fields.UUID(dump_only=True)
    amount = fields.Decimal(as_string=True, dump_only=True)
    note = fields.Str(dump_only=True, allow_none=True)
    occurred_at = fields.Date(dump_only=True)
    created_at = fields.DateTime(dump_only=True)
