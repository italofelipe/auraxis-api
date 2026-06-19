from __future__ import annotations

from typing import Any, cast

from flask import Response, request
from flask_apispec.views import MethodResource

from app.application.services.authenticated_user_context_service import (
    AuthenticatedUserContextService,
)
from app.auth import get_active_auth_context
from app.docs.openapi_helpers import (
    contract_header_param,
    json_error_response,
    json_success_response,
)
from app.extensions.integration_metrics import increment_metric
from app.models.transaction import Transaction
from app.services.authenticated_user_payloads import (
    to_authenticated_user_canonical_payload,
)
from app.utils.pagination import PaginatedResponse
from app.utils.response_builder import json_response, success_payload
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required

from .contracts import compat_success, is_v3_contract_request
from .helpers import (
    _validation_error_response,
    filter_transactions,
    validate_user_token,
)
from .presenters import to_user_profile_payload, to_wallet_payload

COLLECTION_QUERY_PARAMS = ("page", "limit", "status", "month")
USER_ME_LEGACY_SUNSET = "Tue, 30 Jun 2026 23:59:59 GMT"
USER_ME_LEGACY_WARNING = (
    '299 - "/user/me legacy contract is deprecated; migrate to '
    'X-API-Contract: v3 or GET /user/bootstrap"'
)


def _has_collection_semantics() -> bool:
    return any(request.args.get(field) is not None for field in COLLECTION_QUERY_PARAMS)


def _apply_legacy_contract_deprecation_headers(
    response: Response,
    *,
    has_collection_semantics: bool,
) -> Response:
    increment_metric("http.request.user_me.legacy")
    if has_collection_semantics:
        increment_metric("http.request.user_me.legacy.collection_semantics")
    else:
        increment_metric("http.request.user_me.legacy.no_collection_semantics")

    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = USER_ME_LEGACY_SUNSET
    response.headers["Warning"] = USER_ME_LEGACY_WARNING
    response.headers["X-Auraxis-Successor-Contract"] = "v3"
    response.headers["X-Auraxis-Successor-Endpoint"] = "/user/bootstrap"
    return response


def _parse_positive_int_compat(
    raw_value: str | None,
    *,
    default: int,
    field_name: str,
    max_value: int,
) -> int:
    # Preserve legacy monkeypatch target:
    # app.controllers.user_controller._parse_positive_int
    from app.controllers import user_controller as legacy_user_controller

    return legacy_user_controller._parse_positive_int(
        raw_value,
        default=default,
        field_name=field_name,
        max_value=max_value,
    )


class UserMeResource(MethodResource):
    @doc(
        summary="Obter contexto do usuário autenticado",
        description=(
            "Retorna o contexto do usuário autenticado.\n\n"
            "Uso recomendado:\n"
            "- `X-API-Contract: v3` para o contrato canônico e leve\n"
            "- `/user/bootstrap` para agregado da home\n"
            "- `/transactions` para coleção paginada e filtros\n\n"
            "Legado:\n"
            "- `v1`/`v2` ainda aceitam paginação e filtros de coleção\n"
            "- respostas legadas enviam headers de deprecação e sunset"
        ),
        tags=["Usuário"],
        security=[{"BearerAuth": []}],
        params={
            "page": {"description": "Número da página", "type": "integer"},
            "limit": {"description": "Itens por página", "type": "integer"},
            "status": {"description": "Status da transação", "type": "string"},
            "month": {"description": "Mês no formato YYYY-MM", "type": "string"},
            **contract_header_param(
                supported_version="v2_or_v3",
                description=(
                    "Opcional. `v2` mantém o shape legado padronizado; `v3` "
                    "publica o contrato canônico sem coleções."
                ),
            ),
        },
        responses={
            200: json_success_response(
                description="Contexto autenticado retornado com sucesso",
                message="Contexto autenticado retornado com sucesso",
                data_example={
                    "user": {
                        "identity": {
                            "id": "4b2ef64b-b35d-4ea2-a6f2-4ef3cfb295f1",
                            "name": "Italo Chagas",
                            "email": "italo@auraxis.com.br",
                        },
                        "profile": {
                            "gender": "outro",
                            "birth_date": "1990-01-01",
                            "state_uf": "SP",
                            "occupation": "Founder",
                        },
                        "financial_profile": {
                            "monthly_income_net": 1000.0,
                            "monthly_expenses": 500.0,
                            "net_worth": 2000.0,
                            "initial_investment": 200.0,
                            "monthly_investment": 100.0,
                            "investment_goal_date": "2026-12-31",
                        },
                        "investor_profile": {
                            "declared": "conservador",
                            "suggested": "moderado",
                            "quiz_score": 8,
                            "taxonomy_version": "2026.1",
                            "financial_objectives": "crescer",
                        },
                        "product_context": {"entitlements_version": 3},
                    }
                },
            ),
            401: json_error_response(
                description="Token inválido, expirado ou revogado",
                message="Token revogado",
                error_code="UNAUTHORIZED",
                status_code=401,
            ),
        },
    )
    @jwt_required()
    def get(self) -> Response:
        auth_context = get_active_auth_context()
        user_or_response = validate_user_token(auth_context)
        if isinstance(user_or_response, Response):
            return user_or_response
        user = user_or_response

        context_service = AuthenticatedUserContextService.with_defaults()

        if is_v3_contract_request():
            if _has_collection_semantics():
                return _validation_error_response(
                    exc=ValueError("collection semantics not supported"),
                    fallback_message=(
                        "O contrato canônico de '/user/me' não aceita paginação "
                        "nem filtros de coleção. Use '/transactions' ou o "
                        "bootstrap dedicado."
                    ),
                )
            return json_response(
                success_payload(
                    message="Contexto autenticado retornado com sucesso",
                    data={
                        "user": to_authenticated_user_canonical_payload(
                            context_service.build_profile(user)
                        )
                    },
                ),
                status_code=200,
            )

        authenticated_user_context = context_service.build_context(user)

        try:
            page = _parse_positive_int_compat(
                request.args.get("page"),
                default=1,
                field_name="page",
                max_value=10_000,
            )
            limit = _parse_positive_int_compat(
                request.args.get("limit"),
                default=10,
                field_name="limit",
                max_value=100,
            )
        except ValueError as exc:
            return _validation_error_response(
                exc=exc,
                fallback_message="Parâmetros de paginação inválidos.",
            )
        has_collection_semantics = _has_collection_semantics()
        status = request.args.get("status")
        month = request.args.get("month")

        query_or_response = filter_transactions(user.id, status, month)
        if isinstance(query_or_response, Response):
            return query_or_response
        query = query_or_response

        pagination = cast(Any, query.order_by(Transaction.due_date.desc())).paginate(
            page=page, per_page=limit, error_out=False
        )
        transactions = [
            {
                "id": str(t.id),
                "title": t.title,
                "amount": str(t.amount),
                "type": t.type.value,
                "due_date": t.due_date.isoformat(),
                "status": t.status.value,
                "description": t.description,
                "observation": t.observation,
                "is_recurring": t.is_recurring,
                "is_installment": t.is_installment,
                "installment_count": t.installment_count,
                "tag_id": str(t.tag_id) if t.tag_id else None,
                "account_id": str(t.account_id) if t.account_id else None,
                "credit_card_id": str(t.credit_card_id) if t.credit_card_id else None,
                "impact_policy": (
                    t.impact_policy.value
                    if hasattr(t.impact_policy, "value")
                    else str(t.impact_policy or "full")
                ),
                "currency": t.currency,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in pagination.items
        ]
        paginated_transactions = PaginatedResponse.format(
            transactions, pagination.total, pagination.page, pagination.per_page
        )

        user_data = to_user_profile_payload(authenticated_user_context.profile)
        wallet_data = to_wallet_payload(authenticated_user_context.wallet_entries)
        legacy_payload = {
            "user": user_data,
            "transactions": paginated_transactions,
            "wallet": wallet_data,
        }
        response = compat_success(
            legacy_payload=legacy_payload,
            status_code=200,
            message="Dados do usuário retornados com sucesso",
            data={
                "user": user_data,
                "transactions": {
                    "items": paginated_transactions["data"],
                    "total": paginated_transactions["total"],
                    "page": paginated_transactions["page"],
                    "per_page": paginated_transactions["page_size"],
                    "has_next_page": paginated_transactions["has_next_page"],
                },
                "wallet": wallet_data,
            },
            meta={
                "pagination": {
                    "total": paginated_transactions["total"],
                    "page": paginated_transactions["page"],
                    "per_page": paginated_transactions["page_size"],
                    "has_next_page": paginated_transactions["has_next_page"],
                }
            },
        )
        return _apply_legacy_contract_deprecation_headers(
            response,
            has_collection_semantics=has_collection_semantics,
        )
