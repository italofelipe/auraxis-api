from __future__ import annotations

from typing import Any

from flask import Response
from flask_apispec.views import MethodResource

from app.application.services.user_profile_service import simulate_salary_increase
from app.auth import get_active_auth_context
from app.schemas.user_schemas import SalaryIncreaseSimulationRequestSchema
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required
from app.utils.typed_decorators import typed_use_kwargs as use_kwargs

from .avatar_resource import AvatarResource
from .blueprint import user_bp
from .bootstrap_resource import UserBootstrapResource
from .contracts import compat_success
from .delete_me_resource import DeleteMeResource
from .helpers import validate_user_token
from .me_export_resource import MeExportResource
from .me_resource import UserMeResource
from .notification_preferences_resource import NotificationPreferencesResource
from .onboarding_resource import OnboardingCompleteResource
from .profile_resource import UserProfileResource
from .questionnaire_resource import UserQuestionnaireResource

_ROUTES_REGISTERED = False


class UserSalarySimulationResource(MethodResource):
    @doc(
        description="Simula o aumento salarial e recomposição da inflação.",
        tags=["Usuário"],
        security=[{"BearerAuth": []}],
        responses={
            200: {"description": "Simulação realizada com sucesso"},
            400: {"description": "Erro de validação"},
            401: {"description": "Token inválido ou expirado"},
        },
    )
    @jwt_required()
    @use_kwargs(SalaryIncreaseSimulationRequestSchema(), location="json")
    def post(self, **kwargs: Any) -> Response:
        auth_context = get_active_auth_context()
        user_or_response = validate_user_token(auth_context)
        if isinstance(user_or_response, Response):
            return user_or_response

        result = simulate_salary_increase(
            base_salary=kwargs["base_salary"],
            base_date=kwargs["base_date"],
            discounts=kwargs["discounts"],
            target_real_increase=kwargs["target_real_increase"],
        )

        return compat_success(
            legacy_payload={
                "recomposition": str(result["recomposition"]),
                "target": str(result["target"]),
            },
            status_code=200,
            message="Simulação realizada com sucesso",
            data={
                "recomposition": str(result["recomposition"]),
                "target": str(result["target"]),
            },
        )


def register_user_routes() -> None:
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return

    user_bp.add_url_rule(
        "/profile",
        view_func=UserProfileResource.as_view("profile"),
        methods=["GET", "PUT"],
    )
    user_bp.add_url_rule(
        "/profile/questionnaire",
        view_func=UserQuestionnaireResource.as_view("questionnaire"),
        methods=["GET", "POST"],
    )
    user_bp.add_url_rule(
        "/simulate-salary-increase",
        view_func=UserSalarySimulationResource.as_view("simulate_salary_increase"),
        methods=["POST"],
    )
    user_bp.add_url_rule(
        "/bootstrap",
        view_func=UserBootstrapResource.as_view("bootstrap"),
        methods=["GET"],
    )
    user_bp.add_url_rule("/me", view_func=UserMeResource.as_view("me"))
    user_bp.add_url_rule(
        "/me",
        view_func=DeleteMeResource.as_view("delete_me"),
        methods=["DELETE"],
    )
    user_bp.add_url_rule(
        "/me/export",
        view_func=MeExportResource.as_view("me_export"),
        methods=["GET"],
    )
    user_bp.add_url_rule(
        "/notification-preferences",
        view_func=NotificationPreferencesResource.as_view("notification_preferences"),
        methods=["GET", "PATCH"],
    )
    user_bp.add_url_rule(
        "/me/avatar",
        view_func=AvatarResource.as_view("avatar"),
        methods=["POST", "DELETE"],
    )
    user_bp.add_url_rule(
        "/onboarding/complete",
        view_func=OnboardingCompleteResource.as_view("onboarding_complete"),
        methods=["POST"],
    )
    _ROUTES_REGISTERED = True


register_user_routes()
