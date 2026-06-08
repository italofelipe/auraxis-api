from __future__ import annotations

from flask import Response
from flask_apispec.views import MethodResource

from app.auth import get_active_auth_context
from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required

from .contracts import compat_success
from .helpers import validate_user_token


class OnboardingCompleteResource(MethodResource):
    """Persist the onboarding-completed marker for the authenticated user.

    Idempotent: the first call stamps ``onboarding_completed_at``; subsequent
    calls return the existing timestamp without changing it. This lets the web
    client record completion server-side so clearing browser storage on any
    device does not re-trigger the onboarding wizard (#1471).
    """

    @doc(
        description="Marca o onboarding do usuário como concluído (idempotente).",
        tags=["Usuário"],
        security=[{"BearerAuth": []}],
        responses={
            200: {"description": "Onboarding marcado como concluído"},
            401: {"description": "Token inválido ou expirado"},
        },
    )
    @jwt_required()
    def post(self) -> Response:
        auth_context = get_active_auth_context()
        user_or_response = validate_user_token(auth_context)
        if isinstance(user_or_response, Response):
            return user_or_response

        user = user_or_response
        if user.onboarding_completed_at is None:
            user.onboarding_completed_at = utc_now_naive()
            db.session.commit()

        completed_at = user.onboarding_completed_at.isoformat()
        payload = {"onboarding_completed_at": completed_at}
        return compat_success(
            legacy_payload=payload,
            status_code=200,
            message="Onboarding concluído",
            data=payload,
        )
