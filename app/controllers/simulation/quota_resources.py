"""REST resources da quota de simulação (freemium) — #1409.

- ``GET  /simulations/quota``         → snapshot da quota (não consome)
- ``POST /simulations/quota/consume`` → consome 1 simulação (allowed=False se esgotado)
"""

from __future__ import annotations

from typing import Any

from flask_apispec.views import MethodResource

from app.application.services import simulation_quota_service
from app.auth import current_user_id
from app.decorators import require_email_verified
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required

from .contracts import compat_success

_TAGS = ["Simulações"]


class SimulationQuotaResource(MethodResource):
    @doc(
        description="Retorna a quota de simulações do usuário autenticado.",
        tags=_TAGS,
        security=[{"BearerAuth": []}],
        responses={
            200: {"description": "Snapshot da quota"},
            401: {"description": "Token inválido"},
        },
    )
    @jwt_required()
    @require_email_verified
    def get(self) -> Any:
        quota = simulation_quota_service.get_quota(current_user_id())
        return compat_success(
            legacy_payload=dict(quota),
            status_code=200,
            message="Quota de simulação recuperada com sucesso.",
            data=dict(quota),
        )


class SimulationQuotaConsumeResource(MethodResource):
    @doc(
        description=(
            "Consome uma simulação completa. Premium é ilimitado; free esgotado "
            "retorna allowed=false (sem erro) para o cliente exibir o paywall."
        ),
        tags=_TAGS,
        security=[{"BearerAuth": []}],
        responses={
            200: {"description": "Quota atualizada (ver campo allowed)"},
            401: {"description": "Token inválido"},
        },
    )
    @jwt_required()
    @require_email_verified
    def post(self) -> Any:
        quota = simulation_quota_service.consume(current_user_id())
        return compat_success(
            legacy_payload=dict(quota),
            status_code=200,
            message="Quota de simulação atualizada.",
            data=dict(quota),
        )
