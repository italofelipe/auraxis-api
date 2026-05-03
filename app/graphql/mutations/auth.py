from __future__ import annotations

from datetime import timedelta
from typing import Any, NoReturn, cast

import graphene
from flask_jwt_extended import create_access_token, get_jti
from graphql import GraphQLError
from marshmallow import ValidationError
from werkzeug.security import generate_password_hash

from app.application.services.auth_security_policy_service import (
    get_auth_security_policy,
)
from app.application.services.email_confirmation_service import (
    confirm_email,
    issue_email_confirmation,
    resend_email_confirmation,
)
from app.application.services.login_identity_service import resolve_login_identity
from app.application.services.password_reset_service import (
    request_password_reset,
    reset_password,
)
from app.application.services.password_verification_service import (
    verify_password_with_timing_protection,
)
from app.application.services.user_profile_service import update_user_profile
from app.extensions.database import db
from app.extensions.integration_metrics import increment_metric
from app.extensions.jwt_revocation_cache import get_jwt_revocation_cache
from app.graphql.auth import get_current_user_required
from app.graphql.errors import (
    GRAPHQL_ERROR_CODE_AUTH_BACKEND_UNAVAILABLE,
    GRAPHQL_ERROR_CODE_CONFLICT,
    GRAPHQL_ERROR_CODE_TOO_MANY_ATTEMPTS,
    GRAPHQL_ERROR_CODE_UNAUTHORIZED,
    GRAPHQL_ERROR_CODE_VALIDATION,
    build_public_graphql_error,
)
from app.graphql.observability import log_graphql_resolver
from app.graphql.schema_utils import _user_basic_auth_payload, _user_to_graphql_payload
from app.graphql.types import AuthPayloadType, UserType
from app.http.runtime import runtime_logger
from app.models.user import User
from app.schemas.auth_schema import ForgotPasswordSchema, ResetPasswordSchema
from app.schemas.user_schemas import UserRegistrationSchema
from app.services.login_attempt_guard_service import (
    LoginAttemptContext,
    LoginAttemptGuardService,
    LoginGuardBackendUnavailableError,
    build_login_attempt_context,
    get_login_attempt_guard,
)

AUTH_BACKEND_UNAVAILABLE_MESSAGE = (
    "Authentication temporarily unavailable. Try again later."
)


def _public_graphql_error(message: str, *, code: str) -> GraphQLError:
    return build_public_graphql_error(message, code=code)


def _raise_auth_backend_unavailable(exc: Exception) -> NoReturn:
    raise build_public_graphql_error(
        AUTH_BACKEND_UNAVAILABLE_MESSAGE,
        code=GRAPHQL_ERROR_CODE_AUTH_BACKEND_UNAVAILABLE,
    ) from exc


def _guard_check_or_raise(
    *,
    login_guard: LoginAttemptGuardService,
    login_context: LoginAttemptContext,
) -> tuple[bool, int]:
    try:
        return login_guard.check(login_context)
    except LoginGuardBackendUnavailableError as exc:
        _raise_auth_backend_unavailable(exc)


def _guard_register_failure_or_raise(
    *,
    login_guard: LoginAttemptGuardService,
    login_context: LoginAttemptContext,
) -> None:
    try:
        login_guard.register_failure(login_context)
    except LoginGuardBackendUnavailableError as exc:
        _raise_auth_backend_unavailable(exc)


def _guard_register_success_or_raise(
    *,
    login_guard: LoginAttemptGuardService,
    login_context: LoginAttemptContext,
) -> None:
    try:
        login_guard.register_success(login_context)
    except LoginGuardBackendUnavailableError as exc:
        _raise_auth_backend_unavailable(exc)


class RegisterUserMutation(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        email = graphene.String(required=True)
        password = graphene.String(required=True)
        investor_profile = graphene.String()

    Output = AuthPayloadType

    def mutate(
        self,
        info: graphene.ResolveInfo,
        name: str,
        email: str,
        password: str,
        investor_profile: str | None = None,
    ) -> AuthPayloadType:
        auth_policy = get_auth_security_policy()
        registration_schema = UserRegistrationSchema()
        try:
            validated = registration_schema.load(
                {
                    "name": name,
                    "email": email,
                    "password": password,
                    "investor_profile": investor_profile,
                }
            )
        except ValidationError as exc:
            messages = exc.messages
            if isinstance(messages, dict):
                flat = "; ".join(
                    f"{field}: {', '.join(str(item) for item in errors)}"
                    for field, errors in messages.items()
                )
                raise _public_graphql_error(
                    flat or "Dados inválidos para registro.",
                    code=GRAPHQL_ERROR_CODE_VALIDATION,
                ) from exc
            raise _public_graphql_error(
                "Dados inválidos para registro.",
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            ) from exc

        duplicate_user = User.query.filter_by(email=validated["email"]).first()
        if duplicate_user:
            if auth_policy.registration.conceal_conflict:
                return AuthPayloadType(
                    message=auth_policy.registration.accepted_message,
                )
            raise _public_graphql_error(
                auth_policy.registration.conflict_message,
                code=GRAPHQL_ERROR_CODE_CONFLICT,
            )

        user = User(
            name=validated["name"],
            email=validated["email"],
            password=generate_password_hash(validated["password"]),
            investor_profile=validated.get("investor_profile"),
        )
        db.session.add(user)
        db.session.commit()
        try:
            issue_email_confirmation(user)
        except Exception:
            runtime_logger().exception(
                "Failed to dispatch account confirmation email "
                "after GraphQL registration."
            )
        if auth_policy.registration.conceal_conflict:
            return AuthPayloadType(
                message=auth_policy.registration.accepted_message,
            )
        return AuthPayloadType(
            message=auth_policy.registration.created_message,
            user=UserType(**_user_to_graphql_payload(user)),
        )


class LoginMutation(graphene.Mutation):
    class Arguments:
        email = graphene.String(required=True)
        password = graphene.String(required=True)

    Output = AuthPayloadType

    @log_graphql_resolver("login")
    def mutate(
        self,
        info: graphene.ResolveInfo,
        email: str,
        password: str,
    ) -> AuthPayloadType:
        auth_policy = get_auth_security_policy()
        try:
            identity = resolve_login_identity(
                email=email,
                find_user_by_email=lambda value: User.query.filter_by(
                    email=value
                ).first(),
            )
        except ValueError as exc:
            raise _public_graphql_error(
                str(exc),
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            ) from exc
        increment_metric("auth.login.identifier.graphql.email")
        request_obj = cast(dict[str, Any], info.context).get("request")
        headers = request_obj.headers if request_obj is not None else {}
        login_context = build_login_attempt_context(
            principal=identity.principal,
            remote_addr=(
                getattr(request_obj, "remote_addr", None)
                if request_obj is not None
                else None
            ),
            user_agent=headers.get("User-Agent") if headers else None,
            forwarded_for=headers.get("X-Forwarded-For") if headers else None,
            real_ip=headers.get("X-Real-IP") if headers else None,
            known_principal=(
                identity.user is not None
                and auth_policy.login_guard.expose_known_principal
            ),
        )
        login_guard = get_login_attempt_guard()
        allowed, retry_after = _guard_check_or_raise(
            login_guard=login_guard,
            login_context=login_context,
        )
        if not allowed:
            raise build_public_graphql_error(
                "Too many login attempts. Try again later.",
                code=GRAPHQL_ERROR_CODE_TOO_MANY_ATTEMPTS,
                retry_after_seconds=retry_after,
            )

        password_hash = identity.user.password if identity.user is not None else None
        is_valid_password = verify_password_with_timing_protection(
            password_hash=password_hash,
            plain_password=password,
        )
        if not identity.user or not is_valid_password:
            _guard_register_failure_or_raise(
                login_guard=login_guard,
                login_context=login_context,
            )
            raise _public_graphql_error(
                "Invalid credentials",
                code=GRAPHQL_ERROR_CODE_UNAUTHORIZED,
            )

        _guard_register_success_or_raise(
            login_guard=login_guard,
            login_context=login_context,
        )
        token = create_access_token(
            identity=str(identity.user.id), expires_delta=timedelta(hours=1)
        )
        jti = get_jti(token)
        if identity.user.current_jti != jti:
            identity.user.current_jti = jti
            db.session.commit()
        return AuthPayloadType(
            message="Login successful",
            token=token,
            user=UserType(**_user_basic_auth_payload(identity.user)),
        )


class LogoutMutation(graphene.Mutation):
    ok = graphene.Boolean(required=True)
    message = graphene.String(required=True)

    @log_graphql_resolver("logout")
    def mutate(self, info: graphene.ResolveInfo) -> "LogoutMutation":
        user = get_current_user_required()
        user_id = str(user.id)
        user.current_jti = None
        db.session.commit()
        get_jwt_revocation_cache().invalidate(user_id)
        return LogoutMutation(ok=True, message="Logout successful")


class ForgotPasswordMutation(graphene.Mutation):
    class Arguments:
        email = graphene.String(required=True)

    Output = AuthPayloadType

    def mutate(self, info: graphene.ResolveInfo, email: str) -> AuthPayloadType:
        schema = ForgotPasswordSchema()
        try:
            validated = schema.load({"email": email})
        except ValidationError as exc:
            raise _public_graphql_error(
                "Dados inválidos para recuperação de senha.",
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            ) from exc

        result = request_password_reset(str(validated["email"]))
        return AuthPayloadType(message=result.message)


class ResendConfirmationEmailMutation(graphene.Mutation):
    class Arguments:
        email = graphene.String(required=True)

    Output = AuthPayloadType

    def mutate(self, info: graphene.ResolveInfo, email: str) -> AuthPayloadType:
        schema = ForgotPasswordSchema()
        try:
            validated = schema.load({"email": email})
        except ValidationError as exc:
            raise _public_graphql_error(
                "Dados inválidos para confirmacao de conta.",
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            ) from exc

        result = resend_email_confirmation(str(validated["email"]))
        return AuthPayloadType(message=result.message)


class ResetPasswordMutation(graphene.Mutation):
    class Arguments:
        token = graphene.String(required=True)
        new_password = graphene.String(required=True)

    Output = AuthPayloadType

    def mutate(
        self,
        info: graphene.ResolveInfo,
        token: str,
        new_password: str,
    ) -> AuthPayloadType:
        schema = ResetPasswordSchema()
        try:
            validated = schema.load({"token": token, "new_password": new_password})
        except ValidationError as exc:
            raise _public_graphql_error(
                "Dados inválidos para redefinição de senha.",
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            ) from exc

        result = reset_password(
            token=str(validated["token"]),
            new_password_hash=generate_password_hash(str(validated["new_password"])),
        )
        if not result.ok:
            raise _public_graphql_error(
                result.message,
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            )
        return AuthPayloadType(message=result.message)


class ConfirmEmailMutation(graphene.Mutation):
    class Arguments:
        token = graphene.String(required=True)

    Output = AuthPayloadType

    def mutate(self, info: graphene.ResolveInfo, token: str) -> AuthPayloadType:
        result = confirm_email(token=token)
        if not result.ok:
            raise _public_graphql_error(
                result.message,
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            )
        return AuthPayloadType(message=result.message)


class UpdateUserProfileMutation(graphene.Mutation):
    class Arguments:
        gender = graphene.String()
        birth_date = graphene.String()
        monthly_income = graphene.Float()
        monthly_income_net = graphene.Float()
        net_worth = graphene.Float()
        monthly_expenses = graphene.Float()
        initial_investment = graphene.Float()
        monthly_investment = graphene.Float()
        investment_goal_date = graphene.String()
        state_uf = graphene.String()
        occupation = graphene.String()
        investor_profile = graphene.String()
        financial_objectives = graphene.String()
        # B11: quiz-derived suggestion fields
        investor_profile_suggested = graphene.String()
        profile_quiz_score = graphene.Int()
        taxonomy_version = graphene.String()

    user = graphene.Field(UserType, required=True)

    def mutate(
        self, info: graphene.ResolveInfo, **kwargs: Any
    ) -> "UpdateUserProfileMutation":
        user = get_current_user_required()
        payload = dict(kwargs)
        if (
            "monthly_income" not in payload
            and "monthly_income_net" in payload
            and payload.get("monthly_income_net") is not None
        ):
            payload["monthly_income"] = payload["monthly_income_net"]
        result = update_user_profile(user, payload)
        if result["error"]:
            raise _public_graphql_error(
                str(result["error"]),
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            )
        errors = user.validate_profile_data()
        if errors:
            raise _public_graphql_error(
                f"Erro de validação: {errors}",
                code=GRAPHQL_ERROR_CODE_VALIDATION,
            )
        db.session.commit()
        return UpdateUserProfileMutation(
            user=UserType(**_user_to_graphql_payload(user))
        )


class RevokeSessionMutation(graphene.Mutation):
    """Revoke a specific session by ID (multi-device, #1028)."""

    class Arguments:
        session_id = graphene.String(required=True)

    ok = graphene.Boolean(required=True)
    message = graphene.String(required=True)

    def mutate(
        self, info: graphene.ResolveInfo, session_id: str
    ) -> "RevokeSessionMutation":
        from uuid import UUID

        from app.application.services.session_service import (
            SessionNotFoundError,
            revoke_session,
        )

        user = get_current_user_required()
        try:
            revoke_session(session_id=UUID(session_id), user_id=user.id)
        except (ValueError, SessionNotFoundError) as exc:
            raise _public_graphql_error(
                "Session not found.",
                code=GRAPHQL_ERROR_CODE_UNAUTHORIZED,
            ) from exc
        return RevokeSessionMutation(ok=True, message="Session revoked")


class RevokeAllSessionsMutation(graphene.Mutation):
    """Revoke all active sessions — global logout (#1028)."""

    ok = graphene.Boolean(required=True)
    revoked = graphene.Int(required=True)

    def mutate(self, info: graphene.ResolveInfo) -> "RevokeAllSessionsMutation":
        from app.application.services.session_service import revoke_all_sessions

        user = get_current_user_required()
        count = revoke_all_sessions(user_id=user.id)
        return RevokeAllSessionsMutation(ok=True, revoked=count)
