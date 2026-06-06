"""ai7 — allow 'spending_patterns' in ai_insights.insight_type CHECK (#1455).

The Radar de Gastos (spending-patterns) moves from on-demand LLM calls to a
cron-generated, cached insight. Caching reuses the ``ai_insights`` table, so the
``ck_ai_insights_type`` CHECK constraint must accept the new ``spending_patterns``
value alongside the existing daily/weekly/monthly/recap values.

The column is a plain VARCHAR(20) + named CHECK (``native_enum=False``), so no
PostgreSQL ``CREATE TYPE`` is involved. On PostgreSQL the constraint is dropped
and recreated in place; on SQLite (test runtime) the table is rebuilt via
``batch_alter_table`` so the CHECK is regenerated from scratch.

Revision ID: ai7
Revises: rs1_recurrence_series_id
Create Date: 2026-06-05

"""

from __future__ import annotations

from alembic import op

revision = "ai7"
down_revision = "rs1_recurrence_series_id"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_ai_insights_type"
_WITH_PATTERNS = "insight_type IN ('daily','weekly','monthly','recap','spending_patterns')"
_WITHOUT_PATTERNS = "insight_type IN ('daily','weekly','monthly','recap')"


def _swap_check(*, condition: str) -> None:
    bind = op.get_context().connection
    if bind.dialect.name == "sqlite":
        # SQLite cannot ALTER a CHECK constraint in place; rebuild the table.
        with op.batch_alter_table("ai_insights", recreate="always") as batch:
            batch.create_check_constraint(_CONSTRAINT, condition)
        return
    op.drop_constraint(_CONSTRAINT, "ai_insights", type_="check")
    op.create_check_constraint(_CONSTRAINT, "ai_insights", condition)


def upgrade() -> None:
    _swap_check(condition=_WITH_PATTERNS)


def downgrade() -> None:
    _swap_check(condition=_WITHOUT_PATTERNS)
