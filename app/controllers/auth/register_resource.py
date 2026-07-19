from __future__ import annotations

from typing import Any

from flask import Response, current_app
from flask_apispec.views import MethodResource

from app.docs.openapi_helpers import (
    contract_header_param,
    json_error_response,
    json_request_body,
    json_success_response,
)
from app.extensions.database import db
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.schemas.user_schemas import UserRegistrationSchema
from app.services.captcha_service import get_captcha_service
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_use_kwargs as use_kwargs

from .contracts import compat_error, compat_success, registration_ack_payload
from .dependencies import get_auth_dependencies


class RegisterResource(MethodResource):
    @doc(
        summary="Registrar usuário",
        description=(
            "Cria uma nova conta no sistema.\n\n"
            "Payload:\n"
            "- `name`, `email` e `password` são obrigatórios\n"
            "- `investor_profile` é opcional no onboarding inicial\n\n"
            "Dependendo da política de segurança, conflitos de email podem ser "
            "neutralizados com uma resposta de aceite para evitar enumeração."
        ),
        tags=["Autenticação"],
        params=contract_header_param(supported_version="v2"),
        requestBody=json_request_body(
            schema=UserRegistrationSchema,
            description="Dados necessários para criação da conta.",
            example={
                "name": "Italo Chagas",
                "email": "italo@auraxis.com.br",
                "password": "MinhaSenha@123",
                "investor_profile": "conservador",
            },
        ),
        responses={
            201: json_success_response(
                description="Usuário criado com sucesso",
                message="User created successfully",
                data_example={
                    "user": {
                        "id": "4b2ef64b-b35d-4ea2-a6f2-4ef3cfb295f1",
                        "name": "Italo Chagas",
                        "email": "italo@auraxis.com.br",
                    }
                },
            ),
            400: json_error_response(
                description="Erro de validação",
                message="Erro de validação",
                error_code="VALIDATION_ERROR",
                status_code=400,
            ),
            409: json_error_response(
                description="Email já registrado",
                message="Email já registrado",
                error_code="CONFLICT",
                status_code=409,
            ),
            500: json_error_response(
                description="Erro interno do servidor",
                message="Failed to create user",
                error_code="INTERNAL_ERROR",
                status_code=500,
            ),
        },
    )
    @use_kwargs(UserRegistrationSchema, location="json")
    def post(self, **validated_data: Any) -> Response:
        captcha_token: str | None = validated_data.pop("captcha_token", None)
        if not get_captcha_service().verify(captcha_token):
            return compat_error(
                legacy_payload={"message": "CAPTCHA verification failed"},
                status_code=400,
                message="CAPTCHA verification failed",
                error_code="CAPTCHA_INVALID",
            )

        dependencies = get_auth_dependencies()
        auth_policy = dependencies.get_auth_security_policy()
        duplicate_user = dependencies.find_user_by_email(validated_data["email"])
        if duplicate_user:
            if auth_policy.registration.conceal_conflict:
                return compat_success(
                    legacy_payload=registration_ack_payload(
                        auth_policy.registration.accepted_message
                    ),
                    status_code=201,
                    message=auth_policy.registration.accepted_message,
                    data={},
                )
            return compat_error(
                legacy_payload={
                    "message": auth_policy.registration.conflict_message,
                    "data": None,
                },
                status_code=409,
                message=auth_policy.registration.conflict_message,
                error_code="CONFLICT",
            )

        try:
            hashed_password = dependencies.hash_password(validated_data["password"])
            user = User(
                name=validated_data["name"],
                email=validated_data["email"],
                password=hashed_password,
                investor_profile=validated_data.get("investor_profile"),
            )
            db.session.add(user)
            db.session.flush()

            # #1569: new accounts start on Free. The 7-day trial moved to the
            # payment gateway (AbacatePay product `trialDays: 7`), so it now
            # requires a tokenised card and is granted by the
            # `subscription.trial_started` webhook — not by signing up.
            # Supersedes H-PROD-01, whose 14-day no-card trial both contradicted
            # the published Terms of Use and would have stacked to 21 free days.
            free_subscription = Subscription(
                user_id=user.id,
                plan_code="free",
                status=SubscriptionStatus.FREE,
            )
            db.session.add(free_subscription)

            # #890: seed default tags for the new user
            from app.models.tag import seed_default_tags

            seed_default_tags(user.id)

            db.session.commit()

            # Sync free-tier entitlements for the new account (#1569: the trial
            # entitlements now arrive with the subscription.trial_started webhook).
            from app.services.entitlement_service import (
                sync_entitlements_from_subscription,
            )

            try:
                sync_entitlements_from_subscription(free_subscription)
                db.session.commit()
            except Exception:
                current_app.logger.warning(
                    "Failed to sync entitlements for user %s", user.id
                )

            try:
                dependencies.issue_email_confirmation(user)
            except Exception:
                current_app.logger.exception(
                    "Failed to dispatch account confirmation email after registration."
                )

            if auth_policy.registration.conceal_conflict:
                return compat_success(
                    legacy_payload=registration_ack_payload(
                        auth_policy.registration.accepted_message
                    ),
                    status_code=201,
                    message=auth_policy.registration.accepted_message,
                    data={},
                )

            user_data = {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                # New registrations are always unconfirmed.
                "email_confirmed": False,
            }
            return compat_success(
                legacy_payload={
                    "message": auth_policy.registration.created_message,
                    "data": user_data,
                },
                status_code=201,
                message=auth_policy.registration.created_message,
                data={"user": user_data},
            )
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to create user.")
            return compat_error(
                legacy_payload={"message": "Failed to create user"},
                status_code=500,
                message="Failed to create user",
                error_code="INTERNAL_ERROR",
            )
