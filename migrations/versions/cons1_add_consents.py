"""cons1 — create consents table (issue #1259).

LGPD versioned consent log. Append-only: each row represents a grant or
revocation event of a specific consent kind at a specific version. The
latest event per (user, kind) determines current status.

Revision ID: cons1
Revises: ai5
Create Date: 2026-05-17

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "cons1"
down_revision = "ai5"
branch_labels = None
depends_on = None


_KIND_VALUES = ("terms", "privacy", "cookies", "ai", "marketing")
_ACTION_VALUES = ("granted", "revoked")
_SOURCE_VALUES = ("web", "app", "api", "system")


def _quoted_in_clause(values: tuple[str, ...]) -> str:
    """Render a SQL ``IN (...)`` clause with single-quoted values."""
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _has_table(name: str) -> bool:
    """Return True when *name* already exists in the database."""
    inspector = sa.inspect(op.get_context().connection)
    return name in inspector.get_table_names()


def upgrade() -> None:
    # Idempotent: prod drift may already carry this table from a partial run;
    # skip so `flask db upgrade` reconciles instead of failing with
    # "relation already exists". On a fresh DB the table+indexes are created.
    if _has_table("consents"):
        return

    op.create_table(
        "consents",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.String(32),
            sa.CheckConstraint(
                f"kind IN {_quoted_in_clause(_KIND_VALUES)}",
                name="ck_consents_kind",
            ),
            nullable=False,
        ),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column(
            "action",
            sa.String(16),
            sa.CheckConstraint(
                f"action IN {_quoted_in_clause(_ACTION_VALUES)}",
                name="ck_consents_action",
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(16),
            sa.CheckConstraint(
                f"source IN {_quoted_in_clause(_SOURCE_VALUES)}",
                name="ck_consents_source",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime,
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_consents_user_id", "consents", ["user_id"])
    op.create_index("ix_consents_created_at", "consents", ["created_at"])
    op.create_index("ix_consents_user_kind", "consents", ["user_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_consents_user_kind", table_name="consents")
    op.drop_index("ix_consents_created_at", table_name="consents")
    op.drop_index("ix_consents_user_id", table_name="consents")
    op.drop_table("consents")
