"""REST resources for LLM-powered AI advisory endpoints (#1206).

Endpoints:
  GET  /ai/insights/spending?month=YYYY-MM  — monthly spending insights
  POST /ai/goals/<goal_id>/projection       — goal projection narrative
  GET  /ai/insights/weekly-summary          — weekly summary narrative

All endpoints require a valid JWT and the "advanced_simulations" entitlement.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from flask import Response, request
from flask_apispec.views import MethodResource
from marshmallow import ValidationError

from app.application.services.ai_insight_feedback_service import (
    AIInsightFeedbackError,
    submit_insight_feedback,
)
from app.auth import current_user_id
from app.controllers.response_contract import (
    compat_error_response,
    compat_success_response,
)
from app.controllers.transaction.utils import _guard_revoked_token
from app.docs.openapi_helpers import (
    json_error_response,
    json_request_body,
    json_success_response,
)
from app.middleware.ai_rate_limit import ai_daily_limit
from app.schemas.ai_insight_feedback_schema import AIInsightFeedbackSchema
from app.schemas.ai_insight_schema import (
    AIInsightGenerateRequestSchema,
    AIMonthlyReportRequestSchema,
)
from app.services.ai_advisory_service import (
    AIAdvisoryService,
    AIInsightCostBudgetExceededError,
)
from app.services.ai_lgpd import AIConsentRequiredError, ensure_ai_consent_granted
from app.services.ai_monthly_report_service import (
    create_monthly_report_run,
    enqueue_monthly_report_run,
    get_ai_insight_by_id,
    get_monthly_report_run_status,
    process_monthly_report_run,
)
from app.services.entitlement_service import has_entitlement
from app.services.llm_provider import LLMProviderError
from app.utils import timezone_utils
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required

log = logging.getLogger(__name__)

_ENTITLEMENT_KEY = "advanced_simulations"
_AI_INSIGHT_PERIOD_TYPES = {"daily", "weekly", "monthly"}
_ANCHOR_DATE_FORMAT_ERROR = "anchor_date deve estar no formato YYYY-MM-DD"


def _check_entitlement(user_id: UUID) -> Response | None:
    """Return 403 response if user lacks the required entitlement, else None."""
    if not has_entitlement(user_id, _ENTITLEMENT_KEY):
        return compat_error_response(
            legacy_payload={"error": "Recurso exclusivo para assinantes Premium."},
            status_code=403,
            message="Recurso exclusivo para assinantes Premium.",
            error_code="ENTITLEMENT_REQUIRED",
        )
    return None


def _ai_consent_required_response(exc: AIConsentRequiredError) -> Response:
    """Standard 403 mapping for ``AIConsentRequiredError`` (#1258 — LGPD)."""
    return compat_error_response(
        legacy_payload={"error": exc.message},
        status_code=403,
        message=exc.message,
        error_code=AIConsentRequiredError.error_code,
    )


def _parse_goal_projection_body(
    goal_id_raw: str,
    body: dict[str, Any],
) -> tuple[Response, None, None, None] | tuple[None, UUID, Decimal, str]:
    """Validate the goal projection request payload.

    Returns either ``(error_response, None, None, None)`` when something is invalid
    or ``(None, parsed_goal_id, monthly_contribution, user_context)`` on
    success. Extracted from :meth:`AIGoalProjectionResource.post` so the
    controller method stays under the cognitive-complexity threshold.
    """
    try:
        parsed_goal_id: UUID = uuid.UUID(goal_id_raw)
    except (ValueError, AttributeError):
        return (
            compat_error_response(
                legacy_payload={"error": "goal_id inválido"},
                status_code=400,
                message="goal_id inválido",
                error_code="VALIDATION_ERROR",
            ),
            None,
            None,
            None,
        )

    user_context = str(body.get("user_context", ""))
    raw_contribution = body.get("monthly_contribution")
    if raw_contribution is None:
        return (
            compat_error_response(
                legacy_payload={"error": "monthly_contribution é obrigatório"},
                status_code=400,
                message="monthly_contribution é obrigatório",
                error_code="VALIDATION_ERROR",
            ),
            None,
            None,
            None,
        )

    try:
        monthly_contribution = Decimal(str(raw_contribution))
        if monthly_contribution < 0:
            raise ValueError("negative")
    except (InvalidOperation, ValueError):
        return (
            compat_error_response(
                legacy_payload={
                    "error": "monthly_contribution deve ser um número positivo"
                },
                status_code=400,
                message="monthly_contribution deve ser um número positivo",
                error_code="VALIDATION_ERROR",
            ),
            None,
            None,
            None,
        )

    return None, parsed_goal_id, monthly_contribution, user_context


def _parse_ai_insight_generate_body(
    body: dict[str, Any],
) -> tuple[Response, None, None, None] | tuple[None, str, date | None, UUID | None]:
    period_type = str(body.get("period_type", "")).strip().lower()
    if period_type not in _AI_INSIGHT_PERIOD_TYPES:
        return (
            compat_error_response(
                legacy_payload={
                    "error": "period_type deve ser daily, weekly ou monthly"
                },
                status_code=400,
                message="period_type deve ser daily, weekly ou monthly",
                error_code="VALIDATION_ERROR",
            ),
            None,
            None,
            None,
        )

    raw_anchor_date = body.get("anchor_date")
    anchor_date: date | None = None
    if raw_anchor_date not in (None, ""):
        try:
            anchor_date = date.fromisoformat(str(raw_anchor_date))
        except ValueError:
            return (
                compat_error_response(
                    legacy_payload={"error": _ANCHOR_DATE_FORMAT_ERROR},
                    status_code=400,
                    message=_ANCHOR_DATE_FORMAT_ERROR,
                    error_code="VALIDATION_ERROR",
                ),
                None,
                None,
                None,
            )

    raw_preview_run_id = body.get("preview_run_id")
    if raw_preview_run_id in (None, ""):
        return None, period_type, anchor_date, None

    try:
        preview_run_id = uuid.UUID(str(raw_preview_run_id))
    except (TypeError, ValueError):
        return (
            compat_error_response(
                legacy_payload={"error": "preview_run_id deve ser um UUID válido"},
                status_code=400,
                message="preview_run_id deve ser um UUID válido",
                error_code="VALIDATION_ERROR",
            ),
            None,
            None,
            None,
        )

    return None, period_type, anchor_date, preview_run_id


def _raw_ai_insight_request_timezone(body: dict[str, Any]) -> object:
    raw_timezone = request.headers.get(timezone_utils.USER_TIMEZONE_HEADER)
    if raw_timezone in (None, ""):
        raw_timezone = body.get("timezone")
    return raw_timezone


def _resolve_ai_insight_request_timezone(
    body: dict[str, Any],
) -> timezone_utils.UserTimezoneResolution:
    return timezone_utils.resolve_user_timezone(_raw_ai_insight_request_timezone(body))


def _parse_optional_iso_date(value: object) -> tuple[Response | None, date | None]:
    if value in (None, ""):
        return None, None
    try:
        return None, date.fromisoformat(str(value))
    except ValueError:
        return (
            compat_error_response(
                legacy_payload={"error": _ANCHOR_DATE_FORMAT_ERROR},
                status_code=400,
                message=_ANCHOR_DATE_FORMAT_ERROR,
                error_code="VALIDATION_ERROR",
            ),
            None,
        )


def _parse_uuid_param(
    raw: str, *, field_name: str
) -> tuple[Response | None, UUID | None]:
    try:
        return None, uuid.UUID(str(raw))
    except (TypeError, ValueError):
        return (
            compat_error_response(
                legacy_payload={"error": f"{field_name} deve ser um UUID válido"},
                status_code=400,
                message=f"{field_name} deve ser um UUID válido",
                error_code="VALIDATION_ERROR",
            ),
            None,
        )


class AIInsightGenerateResource(MethodResource):
    """POST /ai/insights/generate — period-aware AI financial insights."""

    @doc(
        summary="Gerar insight financeiro period-aware com IA (Premium)",
        description=(
            "Gera insights financeiros com contexto daily, weekly ou monthly, "
            "incluindo evidências estruturadas extraídas do snapshot financeiro."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        params={
            timezone_utils.USER_TIMEZONE_HEADER: {
                "in": "header",
                "description": (
                    "Timezone IANA do usuário. Usado para calcular anchor_date "
                    "quando a data âncora é omitida."
                ),
                "type": "string",
                "required": False,
                "example": "America/Sao_Paulo",
            }
        },
        requestBody=json_request_body(
            schema=AIInsightGenerateRequestSchema,
            description="Período que deve ser consolidado antes da chamada à IA.",
            example={
                "period_type": "daily",
                "anchor_date": None,
                "timezone": "America/Sao_Paulo",
                "preview_run_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        ),
        responses={
            200: json_success_response(
                description="Insight gerado com sucesso",
                message="Insight financeiro gerado com sucesso",
                data_example={
                    "period_type": "daily",
                    "period_label": "2026-05-17",
                    "period_start": "2026-05-17",
                    "period_end": "2026-05-17",
                    "summary": "Resumo do período.",
                    "items": [
                        {
                            "type": "saude_financeira",
                            "dimension": "general",
                            "title": "Saldo positivo",
                            "message": "Você terminou o período com saldo positivo.",
                            "evidence": ["current_period.paid.balance"],
                        }
                    ],
                    "context_version": "financial_insight_snapshot.v1",
                    "context_hash": "sha256",
                    "cached": False,
                    "model": "gpt-4o-mini",
                    "tokens_used": 420,
                    "cost_usd": 0.000063,
                    "lead": {
                        "severity": "ok",
                        "read_min": 15,
                        "title": "Saldo positivo no período.",
                        "lead": "Você terminou o período com saldo positivo.",
                        "next_step": "Continue acompanhando os gastos da semana.",
                    },
                },
            ),
            400: json_error_response(
                description="Parâmetros inválidos",
                message="period_type deve ser daily, weekly ou monthly",
                error_code="VALIDATION_ERROR",
                status_code=400,
            ),
            403: json_error_response(
                description="Entitlement insuficiente",
                message="Recurso exclusivo para assinantes Premium.",
                error_code="ENTITLEMENT_REQUIRED",
                status_code=403,
            ),
            500: json_error_response(
                description="Erro interno ou falha do provider LLM",
                message="Erro ao gerar insight financeiro",
                error_code="INTERNAL_ERROR",
                status_code=500,
            ),
        },
    )
    @jwt_required()
    @ai_daily_limit()
    def post(self) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_id = current_user_id()

        entitlement_error = _check_entitlement(user_id)
        if entitlement_error is not None:
            return entitlement_error

        body = request.get_json(silent=True) or {}
        parse_error, period_type, anchor_date, preview_run_id = (
            _parse_ai_insight_generate_body(body)
        )
        if parse_error is not None:
            return parse_error
        assert period_type is not None

        timezone_resolution = _resolve_ai_insight_request_timezone(body)
        anchor_was_omitted = anchor_date is None
        if anchor_was_omitted:
            anchor_date = timezone_utils.local_today(timezone_resolution)

        service = AIAdvisoryService(user_id=user_id)
        timezone_kwargs: dict[str, Any] = {}
        raw_timezone = _raw_ai_insight_request_timezone(body)
        if raw_timezone not in (None, "") or anchor_was_omitted:
            timezone_kwargs = {
                "timezone_name": timezone_resolution.name,
                "timezone_fallback": timezone_resolution.fallback_used,
            }
        try:
            result = service.generate_financial_insights(
                period_type=period_type,
                anchor_date=anchor_date,
                preview_run_id=preview_run_id,
                **timezone_kwargs,
            )
        except AIConsentRequiredError as exc:
            return _ai_consent_required_response(exc)
        except AIInsightCostBudgetExceededError as exc:
            return compat_error_response(
                legacy_payload={"error": str(exc)},
                status_code=429,
                message=str(exc),
                error_code="AI_INSIGHT_BUDGET_EXCEEDED",
            )
        except LLMProviderError as exc:
            return compat_error_response(
                legacy_payload={"error": str(exc)},
                status_code=500,
                message="Erro ao gerar insight financeiro",
                error_code="INTERNAL_ERROR",
            )
        except Exception:
            return compat_error_response(
                legacy_payload={"error": "Erro interno ao gerar insight financeiro"},
                status_code=500,
                message="Erro interno ao gerar insight financeiro",
                error_code="INTERNAL_ERROR",
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=200,
            message="Insight financeiro gerado com sucesso",
            data=result,
        )


class AIInsightChangeStatusResource(MethodResource):
    """GET /ai/insights/change-status — detect snapshot change without the LLM."""

    @doc(
        summary="Verificar se houve mudança desde o último insight (sem IA)",
        description=(
            "Compara o snapshot financeiro atual com o último insight persistido "
            "do mesmo período e retorna `changed`. NÃO chama o LLM: sem custo de "
            "tokens e sem consumir a cota diária. Usado pelo front para confirmar "
            "'nada mudou, gerar mesmo assim?' antes de gastar uma geração."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        params={
            "period_type": {
                "in": "query",
                "description": "daily, weekly ou monthly.",
                "type": "string",
                "required": True,
                "example": "daily",
            },
            "anchor_date": {
                "in": "query",
                "description": "Data âncora ISO (YYYY-MM-DD). Default: hoje.",
                "type": "string",
                "required": False,
                "example": "2026-05-17",
            },
            timezone_utils.USER_TIMEZONE_HEADER: {
                "in": "header",
                "description": "Timezone IANA do usuário (para anchor_date omitido).",
                "type": "string",
                "required": False,
                "example": "America/Sao_Paulo",
            },
        },
        responses={
            200: json_success_response(
                description="Status de mudança calculado",
                message="Status de mudança do insight",
                data_example={
                    "period_type": "daily",
                    "period_label": "2026-05-17",
                    "changed": False,
                    "current_context_hash": "sha256",
                    "last_context_hash": "sha256",
                    "last_generated_at": "2026-05-17T03:15:00",
                },
            ),
            400: json_error_response(
                description="Parâmetros inválidos",
                message="period_type deve ser daily, weekly ou monthly",
                error_code="VALIDATION_ERROR",
                status_code=400,
            ),
        },
    )
    @jwt_required()
    def get(self) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_id = current_user_id()

        period_type = str(request.args.get("period_type", "")).strip().lower()
        if period_type not in _AI_INSIGHT_PERIOD_TYPES:
            return compat_error_response(
                legacy_payload={
                    "error": "period_type deve ser daily, weekly ou monthly"
                },
                status_code=400,
                message="period_type deve ser daily, weekly ou monthly",
                error_code="VALIDATION_ERROR",
            )

        anchor_error, anchor_date = _parse_optional_iso_date(
            request.args.get("anchor_date")
        )
        if anchor_error is not None:
            return anchor_error

        raw_timezone = request.headers.get(
            timezone_utils.USER_TIMEZONE_HEADER
        ) or request.args.get("timezone")
        timezone_resolution = timezone_utils.resolve_user_timezone(raw_timezone)
        anchor_was_omitted = anchor_date is None
        if anchor_was_omitted:
            anchor_date = timezone_utils.local_today(timezone_resolution)

        # Mirror AIInsightGenerateResource: only thread timezone kwargs when a
        # timezone was actually supplied (or the anchor was omitted), so the
        # change-status hash matches what generate would compute for the same
        # request — otherwise the snapshot's timezone metadata diverges.
        timezone_kwargs: dict[str, Any] = {}
        if raw_timezone not in (None, "") or anchor_was_omitted:
            timezone_kwargs = {
                "timezone_name": timezone_resolution.name,
                "timezone_fallback": timezone_resolution.fallback_used,
            }

        service = AIAdvisoryService(user_id=user_id)
        try:
            result = service.financial_insight_change_status(
                period_type=period_type,
                anchor_date=anchor_date,
                **timezone_kwargs,
            )
        except Exception:
            return compat_error_response(
                legacy_payload={"error": "Erro ao verificar mudança do insight"},
                status_code=500,
                message="Erro ao verificar mudança do insight",
                error_code="INTERNAL_ERROR",
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=200,
            message="Status de mudança do insight",
            data=result,
        )


class AISpendingInsightsResource(MethodResource):
    """GET /ai/insights/spending — monthly spending analysis with AI insights."""

    @doc(
        summary="Insights de gastos com IA (Premium)",
        description=(
            "Analisa os gastos do mês informado e retorna insights gerados por LLM em PT-BR. "  # noqa: E501
            "Requer entitlement 'advanced_simulations' (plano Premium)."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        params={
            "month": {
                "in": "query",
                "type": "string",
                "required": False,
                "description": "Mês no formato YYYY-MM. Padrão: mês atual.",
                "example": "2026-05",
            },
        },
        responses={
            200: json_success_response(
                description="Insights gerados com sucesso",
                message="Insights de gastos gerados com sucesso",
                data_example={
                    "insights": (
                        '[{"type":"saude_financeira","title":"Resumo",'
                        '"message":"Mensagem acionável."}]'
                    ),
                    "items": [
                        {
                            "type": "saude_financeira",
                            "title": "Resumo",
                            "message": "Mensagem acionável.",
                        }
                    ],
                    "tokens_used": 320,
                    "cost_usd": 0.000048,
                    "month": "2026-05",
                    "model": "gpt-4o-mini",
                    "cached": False,
                },
            ),
            401: json_error_response(
                description="Não autenticado",
                message="Token inválido",
                error_code="UNAUTHORIZED",
                status_code=401,
            ),
            403: json_error_response(
                description="Entitlement insuficiente",
                message="Recurso exclusivo para assinantes Premium.",
                error_code="ENTITLEMENT_REQUIRED",
                status_code=403,
            ),
            500: json_error_response(
                description="Erro interno ou falha do provider LLM",
                message="Erro ao gerar insights de gastos",
                error_code="INTERNAL_ERROR",
                status_code=500,
            ),
        },
    )
    @jwt_required()
    @ai_daily_limit()
    def get(self) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_id = current_user_id()

        entitlement_error = _check_entitlement(user_id)
        if entitlement_error is not None:
            return entitlement_error

        month = request.args.get("month") or None

        service = AIAdvisoryService(user_id=user_id)
        try:
            result = service.generate_spending_insights(month=month)
        except AIConsentRequiredError as exc:
            return _ai_consent_required_response(exc)
        except LLMProviderError as exc:
            return compat_error_response(
                legacy_payload={"error": str(exc)},
                status_code=500,
                message="Erro ao gerar insights de gastos",
                error_code="INTERNAL_ERROR",
            )
        except Exception:
            return compat_error_response(
                legacy_payload={"error": "Erro interno ao gerar insights"},
                status_code=500,
                message="Erro interno ao gerar insights",
                error_code="INTERNAL_ERROR",
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=200,
            message="Insights de gastos gerados com sucesso",
            data=result,
        )


class AIGoalProjectionResource(MethodResource):
    """POST /ai/goals/<goal_id>/projection — narrative for a goal projection."""

    @doc(
        summary="Narrativa de projeção de meta com IA (Premium)",
        description=(
            "Gera uma narrativa motivacional e prática para uma meta financeira específica, "  # noqa: E501
            "combinando projeção matemática com contexto do usuário. "
            "Requer entitlement 'advanced_simulations' (plano Premium)."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        responses={
            200: json_success_response(
                description="Narrativa gerada com sucesso",
                message="Narrativa de projeção gerada com sucesso",
                data_example={
                    "narrative": "Com base no seu plano de aportes...",
                    "tokens_used": 450,
                    "cost_usd": 0.000067,
                    "projection": {"months_to_completion": 24},
                    "model": "gpt-4o-mini",
                },
            ),
            400: json_error_response(
                description="Parâmetros inválidos",
                message="monthly_contribution deve ser um número positivo",
                error_code="VALIDATION_ERROR",
                status_code=400,
            ),
            401: json_error_response(
                description="Não autenticado",
                message="Token inválido",
                error_code="UNAUTHORIZED",
                status_code=401,
            ),
            403: json_error_response(
                description="Entitlement insuficiente",
                message="Recurso exclusivo para assinantes Premium.",
                error_code="ENTITLEMENT_REQUIRED",
                status_code=403,
            ),
            404: json_error_response(
                description="Meta não encontrada",
                message="Meta não encontrada",
                error_code="NOT_FOUND",
                status_code=404,
            ),
            500: json_error_response(
                description="Falha do provider LLM",
                message="Erro ao gerar narrativa de projeção",
                error_code="INTERNAL_ERROR",
                status_code=500,
            ),
        },
    )
    @jwt_required()
    def post(self, goal_id: str) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_id = current_user_id()

        entitlement_error = _check_entitlement(user_id)
        if entitlement_error is not None:
            return entitlement_error

        parsed = _parse_goal_projection_body(goal_id, request.get_json() or {})
        if parsed[0] is not None:
            return parsed[0]
        _, parsed_goal_id, monthly_contribution, user_context = parsed

        service = AIAdvisoryService(user_id=user_id)
        try:
            result = service.generate_goal_projection_narrative(
                goal_id=parsed_goal_id,
                user_context=user_context,
                monthly_contribution=monthly_contribution,
            )
        except AIConsentRequiredError as exc:
            return _ai_consent_required_response(exc)
        except ValueError as exc:
            return compat_error_response(
                legacy_payload={"error": str(exc)},
                status_code=404,
                message="Meta não encontrada",
                error_code="NOT_FOUND",
            )
        except LLMProviderError as exc:
            return compat_error_response(
                legacy_payload={"error": str(exc)},
                status_code=500,
                message="Erro ao gerar narrativa de projeção",
                error_code="INTERNAL_ERROR",
            )
        except Exception:
            return compat_error_response(
                legacy_payload={"error": "Erro interno"},
                status_code=500,
                message="Erro interno ao gerar narrativa",
                error_code="INTERNAL_ERROR",
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=200,
            message="Narrativa de projeção gerada com sucesso",
            data=result,
        )


class AIWeeklySummaryResource(MethodResource):
    """GET /ai/insights/weekly-summary — AI narrative for weekly summary."""

    @doc(
        summary="Briefing semanal com IA (Premium, somente leitura)",
        description=(
            "Retorna o resumo financeiro da semana atual (agregação de "
            "transações) e a narrativa do último insight semanal já gerado pelo "
            "batch agendado. NÃO chama o LLM nem envia email — a geração ocorre "
            "exclusivamente no cron semanal. Quando ainda não há insight, "
            "'narrative' vem vazio. Requer entitlement 'advanced_simulations'."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        responses={
            200: json_success_response(
                description="Resumo semanal retornado com sucesso",
                message="Resumo semanal retornado com sucesso",
                data_example={
                    "narrative": "Esta semana você gastou R$ 1.200...",
                    "tokens_used": 280,
                    "cost_usd": 0.000042,
                    "summary": {"current_week": {}, "previous_week": {}},
                    "model": "gpt-4o-mini",
                    "generated_at": "2026-06-01T03:00:00",
                },
            ),
            401: json_error_response(
                description="Não autenticado",
                message="Token inválido",
                error_code="UNAUTHORIZED",
                status_code=401,
            ),
            403: json_error_response(
                description="Entitlement insuficiente",
                message="Recurso exclusivo para assinantes Premium.",
                error_code="ENTITLEMENT_REQUIRED",
                status_code=403,
            ),
            500: json_error_response(
                description="Erro interno",
                message="Erro ao ler resumo semanal",
                error_code="INTERNAL_ERROR",
                status_code=500,
            ),
        },
    )
    @jwt_required()
    def get(self) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_id = current_user_id()

        entitlement_error = _check_entitlement(user_id)
        if entitlement_error is not None:
            return entitlement_error

        service = AIAdvisoryService(user_id=user_id)
        try:
            result = service.read_weekly_summary_narrative()
        except Exception:
            return compat_error_response(
                legacy_payload={"error": "Erro interno"},
                status_code=500,
                message="Erro ao ler resumo semanal",
                error_code="INTERNAL_ERROR",
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=200,
            message="Resumo semanal retornado com sucesso",
            data=result,
        )


class AIMonthlyReportResource(MethodResource):
    """POST /ai/insights/monthly-report — async monthly AI report."""

    @doc(
        summary="Solicitar relatório mensal com IA (Premium)",
        description=(
            "Cria um run auditável para relatório mensal, consolida daily insights "
            "do mês, compara com o relatório mensal anterior e envia email com "
            "deep link quando a geração terminar."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        requestBody=json_request_body(
            schema=AIMonthlyReportRequestSchema,
            description="Mês que deve ser consolidado pelo relatório mensal.",
            example={"anchor_date": "2026-05-21", "enqueue": True},
            required=False,
        ),
        responses={
            200: json_success_response(
                description="Relatório gerado no fallback síncrono",
                message="Relatório mensal gerado com sucesso",
                data_example={
                    "run_id": "uuid",
                    "status": "generated",
                    "period_type": "monthly",
                    "period_label": "2026-05",
                    "insight_id": "uuid",
                    "deep_link": "https://app.auraxis.com.br/insights?open=uuid",
                },
            ),
            202: json_success_response(
                description="Run mensal enfileirado",
                message="Relatório mensal enfileirado",
                data_example={
                    "run_id": "uuid",
                    "status": "previewed",
                    "period_type": "monthly",
                    "period_label": "2026-05",
                    "queued": True,
                    "job_id": "rq-job-id",
                },
            ),
            403: json_error_response(
                description="Entitlement ou consentimento insuficiente",
                message="Recurso exclusivo para assinantes Premium.",
                error_code="ENTITLEMENT_REQUIRED",
                status_code=403,
            ),
        },
    )
    @jwt_required()
    @ai_daily_limit()
    def post(self) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_id = current_user_id()
        entitlement_error = _check_entitlement(user_id)
        if entitlement_error is not None:
            return entitlement_error

        body = request.get_json(silent=True) or {}
        parse_error, anchor_date = _parse_optional_iso_date(body.get("anchor_date"))
        if parse_error is not None:
            return parse_error

        try:
            ensure_ai_consent_granted(user_id)
            run_payload = create_monthly_report_run(
                user_id=user_id,
                anchor_date=anchor_date,
            )
            run_id = uuid.UUID(str(run_payload["run_id"]))
            should_enqueue = bool(body.get("enqueue", True))
            result = (
                enqueue_monthly_report_run(run_id=run_id)
                if should_enqueue
                else process_monthly_report_run(run_id=run_id)
            )
        except AIConsentRequiredError as exc:
            return _ai_consent_required_response(exc)
        except AIInsightCostBudgetExceededError as exc:
            return compat_error_response(
                legacy_payload={"error": str(exc)},
                status_code=429,
                message=str(exc),
                error_code="AI_INSIGHT_BUDGET_EXCEEDED",
            )
        except LLMProviderError as exc:
            return compat_error_response(
                legacy_payload={"error": str(exc)},
                status_code=500,
                message="Erro ao gerar relatório mensal",
                error_code="INTERNAL_ERROR",
            )
        except Exception:
            log.exception("ai.monthly_report.request_failed user_id=%s", user_id)
            return compat_error_response(
                legacy_payload={"error": "Erro interno ao gerar relatório mensal"},
                status_code=500,
                message="Erro interno ao gerar relatório mensal",
                error_code="INTERNAL_ERROR",
            )

        status_code = 202 if result.get("queued") else 200
        message = (
            "Relatório mensal enfileirado"
            if status_code == 202
            else "Relatório mensal gerado com sucesso"
        )
        return compat_success_response(
            legacy_payload=result,
            status_code=status_code,
            message=message,
            data=result,
        )


class AIInsightRunStatusResource(MethodResource):
    """GET /ai/insights/runs/<run_id> — monthly report run status."""

    @doc(
        summary="Consultar status de run de AI Insight",
        description="Retorna o status rastreável de um run de AI Insight do usuário.",
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        responses={
            200: json_success_response(
                description="Status carregado",
                message="Status do run carregado",
                data_example={
                    "run_id": "uuid",
                    "status": "generated",
                    "insight_id": "uuid",
                    "deep_link": "https://app.auraxis.com.br/insights?open=uuid",
                },
            ),
            404: json_error_response(
                description="Run não encontrado",
                message="Run não encontrado",
                error_code="NOT_FOUND",
                status_code=404,
            ),
        },
    )
    @jwt_required()
    def get(self, run_id: str) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        parse_error, parsed_run_id = _parse_uuid_param(run_id, field_name="run_id")
        if parse_error is not None:
            return parse_error
        assert parsed_run_id is not None

        try:
            result = get_monthly_report_run_status(
                user_id=current_user_id(),
                run_id=parsed_run_id,
            )
        except ValueError:
            return compat_error_response(
                legacy_payload={"error": "Run não encontrado"},
                status_code=404,
                message="Run não encontrado",
                error_code="NOT_FOUND",
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=200,
            message="Status do run carregado",
            data=result,
        )


class AIInsightDetailResource(MethodResource):
    """GET /ai/insights/<insight_id> — fetch one insight by id."""

    @doc(
        summary="Buscar AI Insight por id",
        description=(
            "Retorna um insight específico do usuário autenticado, usado por "
            "deep links como /insights?open=<insight_id>."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        responses={
            200: json_success_response(
                description="Insight carregado",
                message="Insight carregado",
                data_example={
                    "id": "uuid",
                    "summary": "Resumo mensal",
                    "period_type": "monthly",
                    "period_label": "2026-05",
                    "items": [],
                },
            ),
            404: json_error_response(
                description="Insight não encontrado",
                message="Insight não encontrado",
                error_code="NOT_FOUND",
                status_code=404,
            ),
        },
    )
    @jwt_required()
    def get(self, insight_id: str) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        parse_error, parsed_insight_id = _parse_uuid_param(
            insight_id,
            field_name="insight_id",
        )
        if parse_error is not None:
            return parse_error
        assert parsed_insight_id is not None

        try:
            result = get_ai_insight_by_id(
                user_id=current_user_id(),
                insight_id=parsed_insight_id,
            )
        except ValueError:
            return compat_error_response(
                legacy_payload={"error": "Insight não encontrado"},
                status_code=404,
                message="Insight não encontrado",
                error_code="NOT_FOUND",
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=200,
            message="Insight carregado",
            data=result,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_history_json_code_fence(content: str) -> str:
    text = content.strip()
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline == -1:
        return text
    text = text[first_newline + 1 :]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    return text.strip()


def _parse_history_content(
    content: str,
) -> tuple[str | None, list[dict[str, Any]], str | None, str | None]:
    try:
        parsed = json.loads(_strip_history_json_code_fence(content))
    except json.JSONDecodeError:
        return None, [], None, None

    if isinstance(parsed, list):
        return None, [item for item in parsed if isinstance(item, dict)], None, None

    if not isinstance(parsed, dict):
        return None, [], None, None

    summary = parsed.get("summary") if isinstance(parsed.get("summary"), str) else None
    raw_items = parsed.get("items")
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    raw_metadata = parsed.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    context_schema_version = metadata.get("context_schema_version")
    context_hash = metadata.get("context_hash")
    return (
        summary,
        items,
        context_schema_version if isinstance(context_schema_version, str) else None,
        context_hash if isinstance(context_hash, str) else None,
    )


class AIInsightHistoryResource(MethodResource):
    """GET /ai/insights/history — paginated AI insight history."""

    @doc(
        summary="Histórico de insights de IA",
        description=(
            "Retorna a lista paginada de insights gerados por IA para o usuário "  # noqa: E501
            "autenticado, ordenada do mais recente para o mais antigo. "
            "Acessível sem entitlement premium."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        params={
            "page": {
                "in": "query",
                "type": "integer",
                "required": False,
                "description": "Número da página (base 1). Padrão: 1.",
                "example": 1,
            },
            "per_page": {
                "in": "query",
                "type": "integer",
                "required": False,
                "description": "Itens por página (máx. 50). Padrão: 20.",
                "example": 20,
            },
        },
        responses={
            200: json_success_response(
                description="Lista de insights",
                message="Histórico de insights carregado",
                data_example={
                    "items": [
                        {
                            "id": "uuid",
                            "content": '{"summary":"Resumo","items":[]}',
                            "summary": "Resumo",
                            "items": [],
                            "period_type": "daily",
                            "insight_type": "daily",
                            "period_label": "2026-05-11",
                            "period_start": "2026-05-11",
                            "period_end": "2026-05-11",
                            "context_schema_version": ("financial_insight_snapshot.v1"),
                            "context_hash": "sha256",
                            "model": "gpt-4o-mini",
                            "tokens_used": 320,
                            "cost_usd": 0.000048,
                            "created_at": "2026-05-11T19:00:00",
                        }
                    ],
                    "page": 1,
                    "per_page": 20,
                    "total": 1,
                },
            ),
            401: json_error_response(
                description="Não autenticado",
                message="Token inválido",
                error_code="UNAUTHORIZED",
                status_code=401,
            ),
        },
    )
    @jwt_required()
    def get(self) -> Response:
        from app.extensions.database import db
        from app.models.ai_insight import AIInsight

        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_id = current_user_id()

        try:
            page = max(1, int(request.args.get("page", 1)))
            per_page = min(50, max(1, int(request.args.get("per_page", 20))))
        except (ValueError, TypeError):
            page, per_page = 1, 20

        total = db.session.query(AIInsight).filter_by(user_id=user_id).count()
        rows = (
            db.session.query(AIInsight)
            .filter_by(user_id=user_id)
            .order_by(AIInsight.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        items = []
        for r in rows:
            summary, insight_items, context_schema_version, context_hash = (
                _parse_history_content(r.content)
            )
            items.append(
                {
                    "id": str(r.id),
                    "content": r.content,
                    "insight_type": r.insight_type.value,
                    "period_type": r.insight_type.value,
                    "period_label": r.period_label,
                    "period_start": r.period_start.isoformat()
                    if r.period_start
                    else None,
                    "period_end": r.period_end.isoformat() if r.period_end else None,
                    "summary": summary,
                    "items": insight_items,
                    "context_schema_version": context_schema_version,
                    "context_hash": context_hash,
                    "model": r.model,
                    "tokens_used": r.tokens_used,
                    "cost_usd": float(r.cost_usd),
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )

        payload = {"items": items, "page": page, "per_page": per_page, "total": total}
        return compat_success_response(
            legacy_payload=payload,
            status_code=200,
            message="Histórico de insights carregado",
            data=payload,
        )


class AIInsightFeedbackResource(MethodResource):
    """POST /ai/insights/<insight_id>/feedback — rate a generated insight."""

    @doc(
        summary="Enviar feedback de um insight de IA",
        description=(
            "Registra notas de 0 a 5 (relevância, veracidade, profundidade, "
            "utilidade) e um comentário opcional sobre um insight do próprio "
            "usuário. Reenviar atualiza o feedback existente."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        params={
            "insight_id": {
                "in": "path",
                "type": "string",
                "required": True,
                "description": "UUID do insight",
            }
        },
        responses={
            201: json_success_response(
                description="Feedback registrado",
                message="Feedback registrado com sucesso",
                data_example={
                    "id": "uuid",
                    "insight_id": "uuid",
                    "relevance": 5,
                    "truthfulness": 4,
                    "depth": 4,
                    "usefulness": 5,
                    "comment": "Muito útil",
                },
            ),
            400: json_error_response(
                description="Dados inválidos",
                message="Dados de feedback inválidos.",
                error_code="VALIDATION_ERROR",
                status_code=400,
            ),
            404: json_error_response(
                description="Insight não encontrado",
                message="Insight não encontrado.",
                error_code="AI_INSIGHT_NOT_FOUND",
                status_code=404,
            ),
        },
    )
    @jwt_required()
    def post(self, insight_id: str) -> Response:
        token_error = _guard_revoked_token()
        if token_error is not None:
            return token_error

        user_id = current_user_id()

        try:
            parsed_insight_id = uuid.UUID(str(insight_id))
        except (ValueError, AttributeError, TypeError):
            return compat_error_response(
                legacy_payload={"error": "insight_id inválido."},
                status_code=400,
                message="insight_id inválido.",
                error_code="VALIDATION_ERROR",
            )

        body = request.get_json(silent=True) or {}
        try:
            data = AIInsightFeedbackSchema().load(body)
        except ValidationError as exc:
            return compat_error_response(
                legacy_payload={"errors": exc.messages},
                status_code=400,
                message="Dados de feedback inválidos.",
                error_code="VALIDATION_ERROR",
            )

        try:
            result = submit_insight_feedback(
                user_id=user_id,
                insight_id=parsed_insight_id,
                data=data,
            )
        except AIInsightFeedbackError as exc:
            return compat_error_response(
                legacy_payload={"error": exc.message},
                status_code=exc.status_code,
                message=exc.message,
                error_code=exc.code,
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=201,
            message="Feedback registrado com sucesso",
            data=result,
        )


__all__ = [
    "AIGoalProjectionResource",
    "AIInsightDetailResource",
    "AIInsightFeedbackResource",
    "AIInsightGenerateResource",
    "AIInsightHistoryResource",
    "AIInsightRunStatusResource",
    "AIMonthlyReportResource",
    "AISpendingInsightsResource",
    "AIWeeklySummaryResource",
]
