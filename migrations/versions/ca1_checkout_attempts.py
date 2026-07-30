"""create checkout_attempts — #1634

Records every attempt to open a paid checkout, so abandonment has a denominator.
``subscriptions`` keeps one row per user with the current state, which means an
attempt that never becomes a payment leaves no trace — and the gateway emits no
abandonment event.

Revision ID: ca1_checkout_attempts
Revises: bo1_account_controls
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "ca1_checkout_attempts"
down_revision = "bo1_account_controls"
branch_labels = None
depends_on = None

TABLE = "checkout_attempts"
STATUSES = ("started", "completed", "failed")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("plan_slug", sa.String(length=60), nullable=False),
        sa.Column("plan_code", sa.String(length=40), nullable=True),
        sa.Column("billing_cycle", sa.String(length=20), nullable=True),
        sa.Column("return_surface", sa.String(length=40), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_checkout_id", sa.String(length=120), nullable=True),
        sa.Column("provider_customer_id", sa.String(length=120), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=120), nullable=True),
        sa.Column(
            "status",
            # VARCHAR + CHECK instead of a native PG enum: a native type makes
            # Alembic emit CREATE TYPE before this migration runs.
            sa.Enum(
                *STATUSES,
                name="checkout_attempt_status",
                native_enum=False,
            ),
            nullable=False,
            server_default="started",
        ),
        sa.Column("failure_reason", sa.String(length=200), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    op.create_index(f"ix_{TABLE}_user_id", TABLE, ["user_id"])
    op.create_index(f"ix_{TABLE}_status", TABLE, ["status"])
    op.create_index(f"ix_{TABLE}_started_at", TABLE, ["started_at"])
    op.create_index(f"ix_{TABLE}_provider_checkout_id", TABLE, ["provider_checkout_id"])
    op.create_index(f"ix_{TABLE}_provider_customer_id", TABLE, ["provider_customer_id"])
    op.create_index(
        f"ix_{TABLE}_provider_subscription_id", TABLE, ["provider_subscription_id"]
    )


def downgrade() -> None:
    for suffix in (
        "provider_subscription_id",
        "provider_customer_id",
        "provider_checkout_id",
        "started_at",
        "status",
        "user_id",
    ):
        op.drop_index(f"ix_{TABLE}_{suffix}", table_name=TABLE)
    op.drop_table(TABLE)
