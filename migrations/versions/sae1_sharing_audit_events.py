"""create sharing_audit_events — #1577

The ``SharingAuditEvent`` model (J13) shipped without an Alembic migration, so
the table only ever existed in dev/test via ``create_all()``.  In production it
was never created, which made ``DELETE /user/me`` (LGPD account deletion) fail
with ``UndefinedTable`` — the anonymisation pass walks every registered entity,
this one included.

Idempotent: tolerate prod/dev drift where the table already exists from a
metadata ``create_all()``.

Revision ID: sae1_sharing_audit_events
Revises: as1_transaction_auto_settle
Create Date: 2026-07-19

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "sae1_sharing_audit_events"
down_revision = "as1_transaction_auto_settle"
branch_labels = None
depends_on = None

TABLE = "sharing_audit_events"


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_context().connection)
    return inspector.has_table(table)


def upgrade() -> None:
    if _has_table(TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_sharing_audit_events_user_id", TABLE, ["user_id"], unique=False
    )
    op.create_index(
        "ix_sharing_audit_events_resource",
        TABLE,
        ["resource_type", "resource_id"],
        unique=False,
    )
    op.create_index(
        "ix_sharing_audit_events_created_at", TABLE, ["created_at"], unique=False
    )


def downgrade() -> None:
    if not _has_table(TABLE):
        return
    op.drop_index("ix_sharing_audit_events_created_at", table_name=TABLE)
    op.drop_index("ix_sharing_audit_events_resource", table_name=TABLE)
    op.drop_index("ix_sharing_audit_events_user_id", table_name=TABLE)
    op.drop_table(TABLE)
