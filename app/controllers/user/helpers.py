from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from flask import Response
from sqlalchemy import extract
from sqlalchemy.orm.query import Query

from app.application.errors import PublicValidationError
from app.application.services.authenticated_user_context_service import (
    AuthenticatedUserContextService,
)
from app.application.services.public_error_mapper_service import (
    map_validation_exception,
)
from app.auth import AuthContext
from app.extensions.database import db
from app.models.transaction import Transaction
from app.models.user import User

from .contracts import compat_error
from .presenters import to_user_profile_payload


def _serialize_user_profile(user: User) -> dict[str, object | None]:
    profile = AuthenticatedUserContextService.with_defaults().build_profile(user)
    return dict(to_user_profile_payload(profile))


def assign_user_profile_fields(
    user: User, data: dict[str, Any]
) -> dict[str, str | bool]:
    date_fields = ["birth_date", "investment_goal_date"]
    for field in [
        "gender",
        "birth_date",
        "monthly_income",
        "net_worth",
        "monthly_expenses",
        "initial_investment",
        "monthly_investment",
        "investment_goal_date",
    ]:
        if field in data:
            value = data[field]
            if field in date_fields and isinstance(value, str):
                try:
                    value = datetime.strptime(value, "%Y-%m-%d").date()
                except ValueError:
                    return {
                        "error": True,
                        "message": (
                            f"Formato inválido para '{field}'. Use 'YYYY-MM-DD'."
                        ),
                    }
            setattr(user, field, value)
    return {"error": False}


def validate_user_token(
    auth_context_or_user_id: AuthContext | UUID,
    jti: str | None = None,
) -> User | Response:
    if isinstance(auth_context_or_user_id, AuthContext):
        user_id = UUID(auth_context_or_user_id.subject)
        token_jti = auth_context_or_user_id.jti
    else:
        user_id = auth_context_or_user_id
        token_jti = jti

    user = cast(User | None, db.session.get(User, user_id))
    if (
        not user
        or token_jti is None
        or not hasattr(user, "current_jti")
        or user.current_jti != token_jti
    ):
        return compat_error(
            legacy_payload={"message": "Token revogado"},
            status_code=401,
            message="Token revogado",
            error_code="UNAUTHORIZED",
        )
    return user


def filter_transactions(
    user_id: UUID, status: str | None, month: str | None
) -> Query[Any] | Response:
    query = cast(
        Query[Any], Transaction.query.filter_by(user_id=user_id, deleted=False)
    )

    if status:
        try:
            from app.models.transaction import TransactionStatus

            query = query.filter(
                Transaction.status == TransactionStatus(status.lower())
            )
        except ValueError:
            return compat_error(
                legacy_payload={"message": f"Status inválido: {status}"},
                status_code=400,
                message=f"Status inválido: {status}",
                error_code="VALIDATION_ERROR",
            )

    if month:
        try:
            year, month_num = map(int, month.split("-"))
            query = query.filter(
                extract("year", Transaction.due_date) == year,
                extract("month", Transaction.due_date) == month_num,
            )
        except ValueError:
            return compat_error(
                legacy_payload={
                    "message": "Parâmetro 'month' inválido. Use o formato YYYY-MM"
                },
                status_code=400,
                message="Parâmetro 'month' inválido. Use o formato YYYY-MM",
                error_code="VALIDATION_ERROR",
            )

    return query


def _parse_positive_int(
    raw_value: str | None,
    *,
    default: int,
    field_name: str,
    max_value: int,
) -> int:
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except ValueError as err:
        raise PublicValidationError(
            f"Parâmetro '{field_name}' inválido. Informe um inteiro positivo."
        ) from err
    if parsed < 1 or parsed > max_value:
        raise PublicValidationError(
            f"Parâmetro '{field_name}' inválido. Use um valor entre 1 e {max_value}."
        )
    return parsed


def _validation_error_response(
    *,
    exc: Exception,
    legacy_key: str = "message",
    fallback_message: str,
) -> Response:
    mapped_error = map_validation_exception(exc, fallback_message=fallback_message)
    return compat_error(
        legacy_payload={legacy_key: mapped_error.message},
        status_code=mapped_error.status_code,
        message=mapped_error.message,
        error_code=mapped_error.code,
        details=mapped_error.details,
    )
