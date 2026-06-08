from __future__ import annotations

from typing import Any
from uuid import UUID

from flask import request
from flask_apispec.views import MethodResource
from marshmallow import fields

from app.application.services.goal_application_service import GoalApplicationError
from app.auth import current_user_id
from app.controllers.response_contract import compat_success_response_deprecated
from app.decorators import require_email_verified
from app.docs.openapi_helpers import deprecated_headers_doc
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required
from app.utils.typed_decorators import typed_use_kwargs as use_kwargs

from .contracts import compat_success, goal_application_error_response
from .dependencies import get_goal_dependencies

GOAL_UPDATE_SUCCESS_MESSAGE = "Meta atualizada com sucesso"
GOAL_UPDATE_SUCCESSOR_ENDPOINT = "/goals/{goal_id}"
GOAL_UPDATE_SUCCESSOR_METHOD = "PATCH"


def _update_goal_data(goal_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
    user_id = current_user_id()
    dependencies = get_goal_dependencies()
    service = dependencies.goal_application_service_factory(user_id)
    return service.update_goal(goal_id, payload)


def _goal_update_response(
    goal_data: dict[str, Any],
    *,
    deprecated: bool,
) -> Any:
    legacy_payload = {
        "message": GOAL_UPDATE_SUCCESS_MESSAGE,
        "goal": goal_data,
    }
    if deprecated:
        return compat_success_response_deprecated(
            legacy_payload=legacy_payload,
            status_code=200,
            message=GOAL_UPDATE_SUCCESS_MESSAGE,
            data={"goal": goal_data},
            successor_endpoint=GOAL_UPDATE_SUCCESSOR_ENDPOINT,
            successor_method=GOAL_UPDATE_SUCCESSOR_METHOD,
        )
    return compat_success(
        legacy_payload=legacy_payload,
        status_code=200,
        message=GOAL_UPDATE_SUCCESS_MESSAGE,
        data={"goal": goal_data},
    )


class GoalCollectionResource(MethodResource):
    @doc(
        description="Cria uma nova meta financeira do usuário autenticado.",
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        responses={
            201: {"description": "Meta criada com sucesso"},
            400: {"description": "Dados inválidos"},
            401: {"description": "Token inválido"},
        },
    )
    @jwt_required()
    @require_email_verified
    def post(self) -> Any:
        user_id = current_user_id()
        payload = request.get_json() or {}
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            goal_data = service.create_goal(payload)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return compat_success(
            legacy_payload={
                "message": "Meta criada com sucesso",
                "goal": goal_data,
            },
            status_code=201,
            message="Meta criada com sucesso",
            data={"goal": goal_data},
        )

    @doc(
        description="Lista metas do usuário autenticado com paginação e filtro.",
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={
            "page": {"in": "query", "type": "integer", "required": False},
            "per_page": {"in": "query", "type": "integer", "required": False},
            "status": {"in": "query", "type": "string", "required": False},
            "X-API-Contract": {
                "in": "header",
                "description": "Opcional. Envie 'v2' para o contrato padronizado.",
                "type": "string",
                "required": False,
            },
        },
        responses={
            200: {"description": "Lista paginada de metas"},
            400: {"description": "Parâmetros inválidos"},
            401: {"description": "Token inválido"},
        },
    )
    @use_kwargs(
        {
            "page": fields.Int(load_default=1, validate=lambda x: x > 0),
            "per_page": fields.Int(load_default=10, validate=lambda x: 0 < x <= 100),
            "status": fields.Str(load_default=None),
        },
        location="query",
    )
    @jwt_required()
    def get(
        self,
        page: int,
        per_page: int,
        status: str | None,
    ) -> Any:
        user_id = current_user_id()
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            result = service.list_goals(
                page=page,
                per_page=per_page,
                status=status,
            )
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        items = result["items"]
        pagination = result["pagination"]
        return compat_success(
            legacy_payload={
                "items": items,
                **pagination,
            },
            status_code=200,
            message="Metas listadas com sucesso",
            data={"items": items},
            meta={"pagination": pagination},
        )


class GoalResource(MethodResource):
    @doc(
        description="Retorna uma meta específica do usuário autenticado.",
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={"goal_id": {"in": "path", "type": "string", "required": True}},
        responses={
            200: {"description": "Meta encontrada"},
            401: {"description": "Token inválido"},
            403: {"description": "Sem permissão"},
            404: {"description": "Meta não encontrada"},
        },
    )
    @jwt_required()
    def get(self, goal_id: UUID) -> Any:
        user_id = current_user_id()
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            goal_data = service.get_goal(goal_id)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return compat_success(
            legacy_payload={"goal": goal_data},
            status_code=200,
            message="Meta retornada com sucesso",
            data={"goal": goal_data},
        )

    @doc(
        description=(
            "Alias legado para atualização de metas. Use `PATCH /goals/{goal_id}` "
            "como contrato canônico para update parcial."
        ),
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={"goal_id": {"in": "path", "type": "string", "required": True}},
        responses={
            200: {
                "description": "Meta atualizada via compatibilidade legada",
                "headers": deprecated_headers_doc(
                    successor_endpoint=GOAL_UPDATE_SUCCESSOR_ENDPOINT,
                    successor_method=GOAL_UPDATE_SUCCESSOR_METHOD,
                ),
            },
            400: {"description": "Dados inválidos"},
            401: {"description": "Token inválido"},
            403: {"description": "Sem permissão"},
            404: {"description": "Meta não encontrada"},
        },
    )
    @jwt_required()
    @require_email_verified
    def put(self, goal_id: UUID) -> Any:
        payload = request.get_json() or {}
        try:
            goal_data = _update_goal_data(goal_id, payload)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return _goal_update_response(goal_data, deprecated=True)

    @doc(
        description="Atualiza parcialmente uma meta específica do usuário autenticado.",
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={"goal_id": {"in": "path", "type": "string", "required": True}},
        responses={
            200: {"description": "Meta atualizada"},
            400: {"description": "Dados inválidos"},
            401: {"description": "Token inválido"},
            403: {"description": "Sem permissão"},
            404: {"description": "Meta não encontrada"},
        },
    )
    @jwt_required()
    @require_email_verified
    def patch(self, goal_id: UUID) -> Any:
        payload = request.get_json() or {}
        try:
            goal_data = _update_goal_data(goal_id, payload)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return _goal_update_response(goal_data, deprecated=False)

    @doc(
        description="Remove uma meta específica do usuário autenticado.",
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={"goal_id": {"in": "path", "type": "string", "required": True}},
        responses={
            200: {"description": "Meta removida"},
            401: {"description": "Token inválido"},
            403: {"description": "Sem permissão"},
            404: {"description": "Meta não encontrada"},
        },
    )
    @jwt_required()
    @require_email_verified
    def delete(self, goal_id: UUID) -> Any:
        user_id = current_user_id()
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            service.delete_goal(goal_id)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return compat_success(
            legacy_payload={"message": "Meta removida com sucesso"},
            status_code=200,
            message="Meta removida com sucesso",
            data={},
        )


class GoalPlanResource(MethodResource):
    @doc(
        description=(
            "Calcula o plano da meta considerando renda, despesas e "
            "capacidade de aporte do usuário."
        ),
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={"goal_id": {"in": "path", "type": "string", "required": True}},
        responses={
            200: {"description": "Planejamento calculado com sucesso"},
            401: {"description": "Token inválido"},
            403: {"description": "Sem permissão"},
            404: {"description": "Meta não encontrada"},
        },
    )
    @jwt_required()
    def get(self, goal_id: UUID) -> Any:
        user_id = current_user_id()
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            result = service.get_goal_plan(goal_id)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return compat_success(
            legacy_payload={
                "goal": result["goal"],
                "goal_plan": result["goal_plan"],
            },
            status_code=200,
            message="Planejamento da meta calculado com sucesso",
            data={
                "goal": result["goal"],
                "goal_plan": result["goal_plan"],
            },
        )


class GoalProjectionResource(MethodResource):
    @doc(
        description=(
            "Retorna a projeção de conclusão da meta com base na taxa de retorno "
            "do portfólio do usuário e no aporte mensal configurado. "
            "Usa juros compostos para calcular o prazo e o aporte sugerido."
        ),
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={"goal_id": {"in": "path", "type": "string", "required": True}},
        responses={
            200: {"description": "Projeção calculada com sucesso"},
            401: {"description": "Token inválido"},
            403: {"description": "Sem permissão"},
            404: {"description": "Meta não encontrada"},
        },
    )
    @jwt_required()
    def get(self, goal_id: UUID) -> Any:
        user_id = current_user_id()
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            result = service.get_goal_projection(goal_id)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return compat_success(
            legacy_payload={
                "goal": result["goal"],
                "projection": result["projection"],
            },
            status_code=200,
            message="Projeção da meta calculada com sucesso",
            data={
                "goal": result["goal"],
                "projection": result["projection"],
            },
        )


class GoalContributionsResource(MethodResource):
    @doc(
        description=(
            "Registra um aporte (valor positivo) ou retirada (valor negativo) "
            "na meta, atualizando o valor acumulado e o histórico."
        ),
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={"goal_id": {"in": "path", "type": "string", "required": True}},
        responses={
            201: {"description": "Contribuição registrada com sucesso"},
            400: {"description": "Dados inválidos ou saldo insuficiente"},
            401: {"description": "Token inválido"},
            403: {"description": "Sem permissão"},
            404: {"description": "Meta não encontrada"},
        },
    )
    @jwt_required()
    @require_email_verified
    def post(self, goal_id: UUID) -> Any:
        user_id = current_user_id()
        payload = request.get_json() or {}
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            result = service.add_contribution(goal_id, payload)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return compat_success(
            legacy_payload={
                "message": "Contribuição registrada com sucesso",
                "goal": result["goal"],
                "contribution": result["contribution"],
            },
            status_code=201,
            message="Contribuição registrada com sucesso",
            data={
                "goal": result["goal"],
                "contribution": result["contribution"],
            },
        )

    @doc(
        description="Lista o histórico de contribuições de uma meta (paginado).",
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        params={
            "goal_id": {"in": "path", "type": "string", "required": True},
        },
        responses={
            200: {"description": "Histórico paginado de contribuições"},
            401: {"description": "Token inválido"},
            403: {"description": "Sem permissão"},
            404: {"description": "Meta não encontrada"},
        },
    )
    @use_kwargs(
        {
            "page": fields.Int(load_default=1, validate=lambda x: x > 0),
            "per_page": fields.Int(load_default=10, validate=lambda x: 0 < x <= 100),
        },
        location="query",
    )
    @jwt_required()
    def get(self, goal_id: UUID, page: int, per_page: int) -> Any:
        user_id = current_user_id()
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            result = service.list_contributions(goal_id, page=page, per_page=per_page)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        items = result["items"]
        pagination = result["pagination"]
        return compat_success(
            legacy_payload={"items": items, **pagination},
            status_code=200,
            message="Histórico de contribuições retornado com sucesso",
            data={"items": items},
            meta={"pagination": pagination},
        )


class GoalSimulationResource(MethodResource):
    @doc(
        description=(
            "Executa simulação de meta sem persistência (what-if), "
            "retornando projeção e recomendações acionáveis."
        ),
        tags=["Metas"],
        security=[{"BearerAuth": []}],
        responses={
            200: {"description": "Simulação calculada com sucesso"},
            400: {"description": "Dados inválidos"},
            401: {"description": "Token inválido"},
        },
    )
    @jwt_required()
    def post(self) -> Any:
        payload = request.get_json() or {}
        user_id = current_user_id()
        dependencies = get_goal_dependencies()
        service = dependencies.goal_application_service_factory(user_id)
        try:
            result = service.simulate_goal_plan(payload)
        except GoalApplicationError as exc:
            return goal_application_error_response(exc)

        return compat_success(
            legacy_payload={"goal_plan": result["goal_plan"]},
            status_code=200,
            message="Simulação da meta calculada com sucesso",
            data={"goal_plan": result["goal_plan"]},
        )
