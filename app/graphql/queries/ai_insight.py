from __future__ import annotations

import json

import graphene

from app.extensions.database import db
from app.graphql.auth import get_current_user_required
from app.models.ai_insight import AIInsight
from app.services.ai_spending_patterns_service import read_latest_spending_patterns


class AIInsightType(graphene.ObjectType):
    id = graphene.ID(required=True)
    content = graphene.String(required=True)
    insight_type = graphene.String(required=True)
    period_label = graphene.String(required=True)
    period_start = graphene.String(required=True)
    period_end = graphene.String(required=True)
    model = graphene.String(required=True)
    tokens_used = graphene.Int(required=True)
    cost_usd = graphene.Float(required=True)
    created_at = graphene.String(required=True)


class AIInsightHistoryResultType(graphene.ObjectType):
    items = graphene.List(graphene.NonNull(AIInsightType), required=True)
    page = graphene.Int(required=True)
    per_page = graphene.Int(required=True)
    total = graphene.Int(required=True)


def _to_ai_insight_type(row: AIInsight) -> AIInsightType:
    return AIInsightType(
        id=str(row.id),
        content=row.content,
        insight_type=row.insight_type.value,
        period_label=row.period_label,
        period_start=row.period_start.isoformat() if row.period_start else "",
        period_end=row.period_end.isoformat() if row.period_end else "",
        model=row.model,
        tokens_used=row.tokens_used,
        cost_usd=float(row.cost_usd),
        created_at=row.created_at.isoformat() if row.created_at else "",
    )


class SpendingPatternsLatestType(graphene.ObjectType):
    """Read-only cached Radar de Gastos (cron-generated, no quota).

    The individual ``patterns`` are forwarded from auraxis-api-v2 and their shape
    is intentionally not pinned here; they are exposed as a JSON string
    (``patterns_json``) so the schema stays stable as v2 evolves. ``generated_at``
    is null when no analysis has been cached yet.
    """

    patterns_json = graphene.String(required=True)
    generated_at = graphene.String()
    period_label = graphene.String()
    model = graphene.String(required=True)
    cost_usd = graphene.Float(required=True)
    tokens_used = graphene.Int(required=True)


class AIInsightQueryMixin:
    ai_insight_history = graphene.Field(
        AIInsightHistoryResultType,
        page=graphene.Int(default_value=1),
        per_page=graphene.Int(default_value=20),
    )
    spending_patterns_latest = graphene.Field(SpendingPatternsLatestType)

    def resolve_spending_patterns_latest(
        self,
        _info: graphene.ResolveInfo,
    ) -> SpendingPatternsLatestType:
        user = get_current_user_required()
        result = read_latest_spending_patterns(user.id)
        return SpendingPatternsLatestType(
            patterns_json=json.dumps(result.get("patterns") or [], ensure_ascii=False),
            generated_at=result.get("generated_at"),
            period_label=result.get("period_label"),
            model=result.get("model") or "",
            cost_usd=float(result.get("cost_usd") or 0.0),
            tokens_used=int(result.get("tokens_used") or 0),
        )

    def resolve_ai_insight_history(
        self,
        _info: graphene.ResolveInfo,
        page: int,
        per_page: int,
    ) -> AIInsightHistoryResultType:
        user = get_current_user_required()
        user_id = user.id

        total = db.session.query(AIInsight).filter_by(user_id=user_id).count()
        rows = (
            db.session.query(AIInsight)
            .filter_by(user_id=user_id)
            .order_by(AIInsight.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        return AIInsightHistoryResultType(
            items=[_to_ai_insight_type(r) for r in rows],
            page=page,
            per_page=per_page,
            total=total,
        )
