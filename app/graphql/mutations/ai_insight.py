"""GraphQL mutation to generate period-aware AI financial insights (MVP-3).

Mirrors `POST /ai/insights/generate`. Each item in the response carries a
`dimension` field (general | transactions | credit_cards | goals | budgets)
so consumers can filter contextually on the UI.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import graphene
from flask import request

from app.application.services.ai_insight_feedback_service import (
    AIInsightFeedbackError,
    submit_insight_feedback,
)
from app.graphql.auth import get_current_user_required
from app.graphql.errors import (
    GRAPHQL_ERROR_CODE_NOT_FOUND,
    GRAPHQL_ERROR_CODE_VALIDATION,
    build_public_graphql_error,
)
from app.graphql.observability import log_graphql_resolver
from app.services.ai_advisory_service import AIAdvisoryService
from app.services.financial_insight_context_builder import INSIGHT_DIMENSIONS
from app.services.llm_provider import LLMProviderError
from app.utils import timezone_utils

_VALID_PERIOD_TYPES = ("daily", "weekly", "monthly")


class AIInsightItemType(graphene.ObjectType):
    """A single LLM-produced insight item, tagged by dimension."""

    type = graphene.String(required=True)
    dimension = graphene.String(required=True)
    title = graphene.String(required=True)
    message = graphene.String(required=True)
    evidence = graphene.List(graphene.String)


class AIInsightRetroEntryType(graphene.ObjectType):
    """One calculated retrospective metric for the Fluida screen (#1501)."""

    key = graphene.String(required=True)
    label = graphene.String(required=True)
    value = graphene.Float(required=True)
    caption = graphene.String(required=True)
    sign = graphene.String(required=True)


class AIInsightSeriesType(graphene.ObjectType):
    """Calculated outflow series: daily over 7 days, weekly over 6 weeks."""

    daily = graphene.List(graphene.Float, required=True)
    weekly = graphene.List(graphene.Float, required=True)


class AIInsightHighlightType(graphene.ObjectType):
    """One calculated per-theme highlight for the Fluida screen (#1501)."""

    label = graphene.String(required=True)
    value = graphene.Float(required=True)
    sub = graphene.String(required=True)


class GenerateAiInsightPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    id = graphene.String()
    period_type = graphene.String()
    period_label = graphene.String()
    period_start = graphene.String()
    period_end = graphene.String()
    summary = graphene.String()
    items = graphene.List(AIInsightItemType)
    context_version = graphene.String()
    cached = graphene.Boolean()
    model = graphene.String()
    tokens_used = graphene.Int()
    cost_usd = graphene.Float()
    forecast = graphene.Boolean()
    # Structured Fluida fields (#1501) — additive, deterministically computed
    # by the backend (paragraphs derive from `summary`).
    paragraphs = graphene.List(graphene.String)
    retro = graphene.List(AIInsightRetroEntryType)
    series = graphene.Field(AIInsightSeriesType)
    highlights = graphene.List(AIInsightHighlightType)


def _to_item_type(item: dict[str, Any]) -> AIInsightItemType:
    return AIInsightItemType(
        type=item.get("type", ""),
        dimension=item.get("dimension", "general"),
        title=item.get("title", ""),
        message=item.get("message", ""),
        evidence=list(item.get("evidence", []) or []),
    )


def _to_retro_entry(entry: dict[str, Any]) -> AIInsightRetroEntryType:
    return AIInsightRetroEntryType(
        key=str(entry.get("key", "")),
        label=str(entry.get("label", "")),
        value=float(entry.get("value", 0.0) or 0.0),
        caption=str(entry.get("caption", "")),
        sign=str(entry.get("sign", "neutral")),
    )


def _to_series_type(series: dict[str, Any] | None) -> AIInsightSeriesType | None:
    if not isinstance(series, dict):
        return None
    return AIInsightSeriesType(
        daily=[float(v) for v in series.get("daily", []) or []],
        weekly=[float(v) for v in series.get("weekly", []) or []],
    )


def _to_highlight_type(highlight: dict[str, Any]) -> AIInsightHighlightType:
    return AIInsightHighlightType(
        label=str(highlight.get("label", "")),
        value=float(highlight.get("value", 0.0) or 0.0),
        sub=str(highlight.get("sub", "")),
    )


class GenerateAiInsightMutation(graphene.Mutation):
    """GraphQL parity for POST /ai/insights/generate.

    Reuses AIAdvisoryService — quota (2x/day Premium), entitlement gate and
    LGPD consent are enforced inside the service. GraphQL surface exposes the
    same payload shape so the frontend hub can render either path identically.
    """

    class Arguments:
        period_type = graphene.String(required=True)
        anchor_date = graphene.String()

    Output = GenerateAiInsightPayload

    @log_graphql_resolver("generateAiInsight")
    def mutate(
        self,
        _info: graphene.ResolveInfo,
        period_type: str,
        anchor_date: str | None = None,
    ) -> GenerateAiInsightPayload:
        user = get_current_user_required()

        normalized = (period_type or "").strip().lower()
        if normalized not in _VALID_PERIOD_TYPES:
            raise build_public_graphql_error(
                "period_type must be one of: " + ", ".join(_VALID_PERIOD_TYPES),
                code="VALIDATION_ERROR",
            )

        parsed_anchor: date | None = None
        if anchor_date:
            try:
                parsed_anchor = datetime.strptime(anchor_date, "%Y-%m-%d").date()
            except ValueError as exc:
                raise build_public_graphql_error(
                    "anchor_date must be ISO YYYY-MM-DD",
                    code="VALIDATION_ERROR",
                ) from exc

        service = AIAdvisoryService(user_id=user.id)
        raw_timezone = request.headers.get(timezone_utils.USER_TIMEZONE_HEADER)
        timezone_kwargs: dict[str, Any] = {}
        if raw_timezone not in (None, "") or parsed_anchor is None:
            timezone_resolution = timezone_utils.resolve_user_timezone(raw_timezone)
            timezone_kwargs = {
                "timezone_name": timezone_resolution.name,
                "timezone_fallback": timezone_resolution.fallback_used,
            }
        try:
            result = service.generate_financial_insights(
                period_type=normalized,
                anchor_date=parsed_anchor,
                **timezone_kwargs,
            )
        except LLMProviderError as exc:
            raise build_public_graphql_error(
                "Erro ao gerar insight financeiro",
                code="LLM_PROVIDER_ERROR",
            ) from exc

        items = [_to_item_type(item) for item in result.get("items", [])]
        # All returned items have a dimension; reject malformed (defensive).
        for item in items:
            if item.dimension not in INSIGHT_DIMENSIONS:
                raise build_public_graphql_error(
                    "Insight item with invalid dimension",
                    code="LLM_PROVIDER_ERROR",
                )

        return GenerateAiInsightPayload(
            ok=True,
            id=result.get("id"),
            period_type=result.get("period_type"),
            period_label=result.get("period_label"),
            period_start=result.get("period_start"),
            period_end=result.get("period_end"),
            summary=result.get("summary"),
            items=items,
            context_version=result.get("context_version"),
            cached=bool(result.get("cached", False)),
            model=result.get("model"),
            tokens_used=int(result.get("tokens_used") or 0),
            cost_usd=float(result.get("cost_usd") or 0),
            forecast=bool(result.get("forecast", False)),
            paragraphs=list(result.get("paragraphs", []) or []),
            retro=[_to_retro_entry(e) for e in result.get("retro", []) or []],
            series=_to_series_type(result.get("series")),
            highlights=[
                _to_highlight_type(h) for h in result.get("highlights", []) or []
            ],
        )


class AIInsightFeedbackPayload(graphene.ObjectType):
    ok = graphene.Boolean(required=True)
    id = graphene.String()
    insight_id = graphene.String()
    relevance = graphene.Int()
    truthfulness = graphene.Int()
    depth = graphene.Int()
    usefulness = graphene.Int()
    comment = graphene.String()


class SubmitAiInsightFeedbackMutation(graphene.Mutation):
    """GraphQL parity for POST /ai/insights/<id>/feedback (#1387)."""

    class Arguments:
        insight_id = graphene.String(required=True)
        relevance = graphene.Int(required=True)
        truthfulness = graphene.Int(required=True)
        depth = graphene.Int(required=True)
        usefulness = graphene.Int(required=True)
        comment = graphene.String()

    Output = AIInsightFeedbackPayload

    @log_graphql_resolver("submitAiInsightFeedback")
    def mutate(
        self,
        _info: graphene.ResolveInfo,
        insight_id: str,
        relevance: int,
        truthfulness: int,
        depth: int,
        usefulness: int,
        comment: str | None = None,
    ) -> "AIInsightFeedbackPayload":
        user = get_current_user_required()

        ratings = {
            "relevance": relevance,
            "truthfulness": truthfulness,
            "depth": depth,
            "usefulness": usefulness,
        }
        for name, value in ratings.items():
            if value is None or not (0 <= int(value) <= 5):
                raise build_public_graphql_error(
                    f"{name} deve estar entre 0 e 5",
                    code=GRAPHQL_ERROR_CODE_VALIDATION,
                )

        try:
            parsed_insight_id = UUID(str(insight_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise build_public_graphql_error(
                "insight_id inválido",
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            ) from exc

        try:
            result = submit_insight_feedback(
                user_id=user.id,
                insight_id=parsed_insight_id,
                data={**ratings, "comment": comment},
            )
        except AIInsightFeedbackError as exc:
            raise build_public_graphql_error(
                exc.message,
                code=GRAPHQL_ERROR_CODE_NOT_FOUND,
            ) from exc

        return AIInsightFeedbackPayload(
            ok=True,
            id=result["id"],
            insight_id=result["insight_id"],
            relevance=result["relevance"],
            truthfulness=result["truthfulness"],
            depth=result["depth"],
            usefulness=result["usefulness"],
            comment=result["comment"],
        )
