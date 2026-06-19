"""Gateway proxy: POST /ai/insights/spending-patterns → auraxis-api-v2 (PROD-04, #567).

New LLM logic lives in auraxis-api-v2 (FastAPI); v1 is being decommissioned and
acts only as an authenticated gateway. This resource enforces the premium
entitlement (the v2 access token carries no tier claim) and forwards the request
— body + Authorization header — to the v2 spending-patterns endpoint.

The v2 base URL comes from the ``AURAXIS_API_V2_BASE_URL`` env var. When it is
unset (e.g. v2 not yet deployed) the endpoint returns 503 rather than failing
obscurely, so clients can degrade gracefully.
"""

from __future__ import annotations

import logging

import requests  # re-exported for test monkeypatching of the underlying client
from flask import Response, request
from flask_apispec.views import MethodResource

from app.auth import current_user_id
from app.controllers.response_contract import (
    compat_error_response,
    compat_success_response,
)
from app.controllers.transaction.utils import _guard_revoked_token
from app.middleware.ai_rate_limit import ai_daily_limit
from app.services.ai_spending_patterns_service import (
    SpendingPatternsUpstreamError,
    call_v2_spending_patterns,
)
from app.services.entitlement_service import has_entitlement
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required

log = logging.getLogger(__name__)

_ENTITLEMENT_KEY = "advanced_simulations"

# Keep ``requests`` referenced so existing tests that monkeypatch
# ``spending_patterns_proxy.requests.post`` continue to patch the same client
# object used by the service layer.
assert requests is not None


class AISpendingPatternsProxyResource(MethodResource):
    """POST /ai/insights/spending-patterns — premium gateway to v2."""

    @doc(
        summary="Radar de gastos compulsivos (Premium)",
        description=(
            "Recebe as transações dos últimos ~90 dias e encaminha para o "
            "auraxis-api-v2, que roda a detecção de padrões via LLM. Requer "
            "entitlement 'advanced_simulations'. Retorna 503 quando a v2 está "
            "indisponível."
        ),
        tags=["AI Advisory"],
        security=[{"BearerAuth": []}],
    )
    @jwt_required()
    @ai_daily_limit()
    def post(self) -> Response:
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

        body = request.get_json(silent=True) or {}
        auth_header = request.headers.get("Authorization", "")

        try:
            status_code, payload = call_v2_spending_patterns(
                transactions=body.get("transactions") or [],
                period_days=int(body.get("period_days") or 90),
                auth_header=auth_header,
            )
        except SpendingPatternsUpstreamError as exc:
            return compat_error_response(
                legacy_payload={"error": "Serviço de insights indisponível."},
                status_code=exc.status_code,
                message=str(exc),
                error_code="SERVICE_UNAVAILABLE",
            )

        if status_code >= 400:
            return compat_error_response(
                legacy_payload=payload or {"error": "Falha no serviço de insights."},
                status_code=status_code,
                message="Falha ao gerar o radar de gastos.",
                error_code="UPSTREAM_ERROR",
            )

        return compat_success_response(
            legacy_payload=payload,
            status_code=200,
            message="Radar de gastos gerado com sucesso",
            data=payload,
        )
