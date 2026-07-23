from __future__ import annotations

from typing import Any
from uuid import UUID

from flask import Response, current_app, request
from flask_apispec.views import MethodResource
from flask_jwt_extended import get_jwt, get_jwt_identity, set_refresh_cookies

from app.application.services.session_service import (
    ConcurrentRefreshError,
    SessionNotFoundError,
    TokenReuseError,
    rotate_session_by_jti,
)
from app.docs.openapi_helpers import (
    contract_header_param,
    json_error_response,
    json_success_response,
)
from app.extensions.database import db
from app.extensions.jwt_revocation_cache import get_jwt_revocation_cache
from app.http.request_context import get_request_context
from app.models.user import User
from app.utils.typed_decorators import typed_doc as doc
from app.utils.typed_decorators import typed_jwt_required as jwt_required

from .contracts import compat_error, compat_success
from .cookie_only_policy import COOKIE_ONLY_HEADER, should_omit_refresh_token_in_body
from .dependencies import get_auth_dependencies

_TOKEN_INVALID_OR_USED_MESSAGE = "Token invalid or already used"


class RefreshTokenResource(MethodResource):
    @doc(
        summary="Renovar access token",
        description=(
            "Emite um novo par de tokens (access + refresh) "
            "usando um refresh token válido.\n\n"
            "Rotation:\n"
            "- Cada uso invalida o refresh token anterior (replay attack prevention).\n"
            "- O novo refresh token tem TTL de 7 dias a partir da emissão.\n\n"
            "Fontes aceitas para o refresh token (SEC-GAP-01):\n"
            "- Cookie httpOnly `auraxis_refresh` (recomendado, clientes novos).\n"
            "- Header `Authorization: Bearer <refresh_token>` (legado).\n\n"
            "Headers:\n"
            "- `X-API-Contract`: opcional; `v2` padroniza o envelope."
        ),
        tags=["Autenticação"],
        params=contract_header_param(supported_version="v2"),
        responses={
            200: json_success_response(
                description="Tokens renovados com sucesso",
                message="Token refreshed",
                data_example={
                    "token": "<access_token>",
                    "refresh_token": "<access_token>",
                },
            ),
            401: json_error_response(
                description="Refresh token inválido, expirado ou já utilizado",
                message=_TOKEN_INVALID_OR_USED_MESSAGE,
                error_code="TOKEN_INVALID",
                status_code=401,
            ),
            429: json_error_response(
                description="Muitas requisições de renovação",
                message="Too many requests",
                error_code="RATE_LIMIT_EXCEEDED",
                status_code=429,
            ),
        },
    )
    @jwt_required(refresh=True)
    def post(self) -> Response:
        user_id: str = get_jwt_identity()
        claims = get_jwt()
        incoming_jti: str = claims.get("jti", "")

        user: User | None = db.session.get(User, UUID(user_id))
        if user is None:
            return compat_error(
                legacy_payload={"message": "User not found"},
                status_code=401,
                message="User not found",
                error_code="TOKEN_INVALID",
            )
        if user.blocked_at is not None:
            return compat_error(
                legacy_payload={"message": "Account blocked"},
                status_code=403,
                message="Account blocked",
                error_code="ACCOUNT_BLOCKED",
            )

        # Replay attack guard: the incoming JTI must match the stored refresh JTI.
        if not incoming_jti or user.refresh_token_jti != incoming_jti:
            return compat_error(
                legacy_payload={"message": _TOKEN_INVALID_OR_USED_MESSAGE},
                status_code=401,
                message=_TOKEN_INVALID_OR_USED_MESSAGE,
                error_code="TOKEN_REUSED",
            )

        try:
            dependencies = get_auth_dependencies()
            new_access_token = dependencies.create_access_token(str(user.id))
            new_refresh_token = dependencies.create_refresh_token(str(user.id))
            new_access_jti = dependencies.get_token_jti(new_access_token)
            new_refresh_jti = dependencies.get_token_jti(new_refresh_token)

            request_context = get_request_context()
            try:
                rotate_session_by_jti(
                    old_jti=incoming_jti,
                    new_raw_refresh_token=new_refresh_token,
                    new_refresh_jti=new_refresh_jti,
                    new_access_jti=new_access_jti,
                    user_agent=request_context.user_agent,
                    remote_addr=request_context.client_ip,
                )
            except TokenReuseError:
                return compat_error(
                    legacy_payload={"message": _TOKEN_INVALID_OR_USED_MESSAGE},
                    status_code=401,
                    message=_TOKEN_INVALID_OR_USED_MESSAGE,
                    error_code="TOKEN_REUSED",
                )
            except ConcurrentRefreshError:
                # Benign concurrent refresh (boot/F5 double-submit): the other
                # request already rotated the token. Reject this one softly with
                # a plain 401 — do NOT revoke the family and do NOT touch user
                # state, so the winning session and other devices stay valid.
                db.session.rollback()
                return compat_error(
                    legacy_payload={"message": _TOKEN_INVALID_OR_USED_MESSAGE},
                    status_code=401,
                    message=_TOKEN_INVALID_OR_USED_MESSAGE,
                    error_code="TOKEN_REUSED",
                )
            except SessionNotFoundError:
                pass  # No RefreshToken row → legacy path, continue.

            # Keep user fields in sync for backward-compat (Redis cache + old clients).
            user.current_jti = new_access_jti
            user.refresh_token_jti = new_refresh_jti
            db.session.commit()
            get_jwt_revocation_cache().set_current_jti(user_id, new_access_jti)

            omit_refresh_in_body = should_omit_refresh_token_in_body(
                header_value=request.headers.get(COOKIE_ONLY_HEADER),
            )
            legacy_payload: dict[str, Any] = {
                "message": "Token refreshed",
                "token": new_access_token,
            }
            data_payload: dict[str, Any] = {
                "token": new_access_token,
            }
            if not omit_refresh_in_body:
                legacy_payload["refresh_token"] = new_refresh_token
                data_payload["refresh_token"] = new_refresh_token
            response = compat_success(
                legacy_payload=legacy_payload,
                status_code=200,
                message="Token refreshed",
                data=data_payload,
            )
            # SEC-1 — rotate the httpOnly refresh cookie; the JSON body stops
            # echoing refresh_token once AURAXIS_REFRESH_COOKIE_ONLY=true or the
            # X-Refresh-Cookie-Only header opts this request into cookie-only.
            set_refresh_cookies(response, new_refresh_token)
            return response
        except Exception:
            current_app.logger.exception(
                "Token refresh failed due to unexpected error."
            )
            return compat_error(
                legacy_payload={"message": "Token refresh failed"},
                status_code=500,
                message="Token refresh failed",
                error_code="INTERNAL_ERROR",
            )
