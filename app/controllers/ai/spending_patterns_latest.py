"""Read-only cached Radar de Gastos: GET /ai/insights/spending-patterns/latest (#1455).

Returns the latest cron-generated spending-patterns analysis WITHOUT calling the
LLM and WITHOUT consuming the per-user AI daily quota. Generation happens only in
the scheduled batch (``flask ai spending-patterns``). When no analysis has been
generated yet, ``patterns`` is empty and ``generated_at`` is ``null`` so the UI can
render a "will be generated" state.

Mirrors :class:`AIWeeklySummaryResource` (jwt only, no ``@ai_daily_limit``).
"""

from __future__ import annotations

import logging

from flask import Response
from flask_apispec.views import MethodResource

from app.auth import current_user_id
from app.controllers.response_contract import (
    compat_error_response,
    compat_success_response,
)
from app.controllers.transaction.utils import _guard_revoked_token
from app.docs.openapi_helpers import json_error_response, json_success_response
from app.services.ai_spending_patterns_service import read_latest_spending_patterns
from app.services.entitlement_service import has_entitlement
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required

log = logging.getLogger(__name__)

_ENTITLEMENT_KEY = "advanced_simulations"


class AISpendingPatternsLatestResource(MethodResource):
    """GET /ai/insights/spending-patterns/latest — cached radar (read-only)."""

    @doc(
        summary="Radar de gastos em cache (Premium, somente leitura)",
        description=(
            "Retorna o último radar de gastos compulsivos já gerado pelo cron "
            "diário. NÃO chama o LLM nem consome a cota diária de IA — a geração "
            "ocorre exclusivamente no batch agendado. Quando ainda não há análise, "
            "'patterns' vem vazio e 'generated_at' é null. Requer entitlement "
            "'advanced_simulations'."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
        responses={
            200: json_success_response(
                description="Radar de gastos em cache retornado com sucesso",
                message="Radar de gastos retornado com sucesso",
                data_example={
                    "patterns": [{"description": "Cafés", "severity": "high"}],
                    "generated_at": "2026-06-05T06:00:00",
                    "period_label": "2026-06-05",
                    "model": "v2-spending-patterns",
                    "cost_usd": 0.000042,
                    "tokens_used": 280,
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
                message="Erro ao ler o radar de gastos",
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

        if not has_entitlement(user_id, _ENTITLEMENT_KEY):
            return compat_error_response(
                legacy_payload={"error": "Recurso exclusivo para assinantes Premium."},
                status_code=403,
                message="Recurso exclusivo para assinantes Premium.",
                error_code="ENTITLEMENT_REQUIRED",
            )

        try:
            result = read_latest_spending_patterns(user_id)
        except Exception:
            log.exception("spending_patterns_latest.read_failed")
            return compat_error_response(
                legacy_payload={"error": "Erro interno"},
                status_code=500,
                message="Erro ao ler o radar de gastos",
                error_code="INTERNAL_ERROR",
            )

        return compat_success_response(
            legacy_payload=result,
            status_code=200,
            message="Radar de gastos retornado com sucesso",
            data=result,
        )
