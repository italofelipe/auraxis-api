from flask import Flask, current_app, request
from flask.typing import ResponseReturnValue
from flask_jwt_extended.exceptions import JWTExtendedException
from jwt.exceptions import PyJWTError

from app.auth import AccountBlockedError, AuthContextError, get_active_auth_context
from app.extensions.jwt_callbacks import _jwt_error_response

_OPEN_ENDPOINTS = {
    "registerresource",
    "authresource",
    "forgotpasswordresource",
    "resetpasswordresource",
    "confirmemailresource",
    "resendconfirmationresource",
    "refreshtokenresource",
    "execute_graphql",
    # Playground handles its own auth (feature flag + admin role check)
    "graphql_playground",
    "static",
    "swaggerui.index",
    "swaggerui.static",
    "swaggerui.swagger_json",
    "swagger-ui",
    "swagger-ui.static",
    "swagger-ui.swagger_json",
    "installment_vs_cash_calculation",
    # Billing webhooks — providers call these directly without JWT.
    # Authenticity is enforced per gateway by BillingWebhookParser.verify.
    "handle_webhook",
    "handle_provider_webhook",
    # Public billing catalog for checkout surfaces
    "list_subscription_plans",
    # Internal observability export guarded by dedicated header token
    "observability_snapshot",
    "observability_metrics",
}


def _is_public_request() -> bool:
    if request.method == "OPTIONS":
        return True
    # Health/readiness endpoints must remain public for infra probes.
    # /readiness performs its own internal bearer-token check.
    if request.path.rstrip("/") in {"/healthz", "/readiness"}:
        return True
    if not request.endpoint:
        return True
    if request.path.startswith("/docs"):
        return True
    return request.endpoint.split(".")[-1] in _OPEN_ENDPOINTS


def _authenticate() -> ResponseReturnValue | None:
    try:
        get_active_auth_context()
    except AccountBlockedError:
        return _jwt_error_response(
            "Conta bloqueada. Entre em contato com o suporte.",
            code="ACCOUNT_BLOCKED",
            status_code=403,
        )
    except (JWTExtendedException, PyJWTError, AuthContextError):
        return _jwt_error_response(
            "Token inválido ou ausente",
            code="UNAUTHORIZED",
            status_code=401,
        )
    except Exception:
        current_app.logger.exception(
            "Unexpected failure while validating JWT in auth guard."
        )
        return _jwt_error_response(
            "Internal Server Error",
            code="INTERNAL_ERROR",
            status_code=500,
        )

    return None


def register_auth_guard(app: Flask) -> None:
    def auth_guard() -> ResponseReturnValue | None:
        if _is_public_request():
            return None
        return _authenticate()

    app.before_request(auth_guard)
