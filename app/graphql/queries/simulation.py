from __future__ import annotations

from typing import Any
from uuid import UUID

import graphene

from app.application.services.installment_vs_cash_application_service import (
    InstallmentVsCashApplicationError,
    InstallmentVsCashApplicationService,
)
from app.application.services.simulation_application_service import (
    SimulationApplicationError,
    SimulationApplicationService,
)
from app.graphql.auth import get_current_user_required
from app.graphql.errors import (
    GRAPHQL_ERROR_CODE_NOT_FOUND,
    GRAPHQL_ERROR_CODE_VALIDATION,
    build_public_graphql_error,
)
from app.graphql.installment_vs_cash_presenters import (
    raise_installment_vs_cash_graphql_error,
    to_installment_vs_cash_calculation_type,
)
from app.graphql.types import InstallmentVsCashCalculationPayloadType


class SimulationType(graphene.ObjectType):
    """Generic persisted simulation envelope (DEC-196 / #1128)."""

    id = graphene.UUID(required=True)
    user_id = graphene.UUID(required=True)
    tool_id = graphene.String(required=True)
    rule_version = graphene.String(required=True)
    inputs = graphene.JSONString(required=True)
    result = graphene.JSONString(required=True)
    metadata = graphene.JSONString()
    saved = graphene.Boolean(required=True)
    created_at = graphene.DateTime(required=True)


class SimulationListPayloadType(graphene.ObjectType):
    items = graphene.List(SimulationType, required=True)
    page = graphene.Int(required=True)
    per_page = graphene.Int(required=True)
    total = graphene.Int(required=True)
    pages = graphene.Int(required=True)


def _to_simulation_type(data: dict[str, Any]) -> SimulationType:
    return SimulationType(
        id=data["id"],
        user_id=data["user_id"],
        tool_id=data["tool_id"],
        rule_version=data["rule_version"],
        inputs=data["inputs"],
        result=data["result"],
        metadata=data.get("metadata"),
        saved=data.get("saved", True),
        created_at=data["created_at"],
    )


def _raise_simulation_graphql_error(exc: SimulationApplicationError) -> None:
    code = (
        GRAPHQL_ERROR_CODE_NOT_FOUND
        if exc.code == "NOT_FOUND"
        else GRAPHQL_ERROR_CODE_VALIDATION
    )
    raise build_public_graphql_error(exc.message, code=code)


class SimulationQuotaType(graphene.ObjectType):
    """Snapshot da quota freemium do simulador (#1409)."""

    limit = graphene.Int(required=True)
    used = graphene.Int(required=True)
    remaining = graphene.Int()  # nulo quando unlimited (premium)
    unlimited = graphene.Boolean(required=True)
    allowed = graphene.Boolean(required=True)
    reset_at = graphene.String(required=True)


def _to_quota_type(data: dict[str, Any]) -> "SimulationQuotaType":
    return SimulationQuotaType(
        limit=data["limit"],
        used=data["used"],
        remaining=data["remaining"],
        unlimited=data["unlimited"],
        allowed=data["allowed"],
        reset_at=data["reset_at"],
    )


class SimulationQueryMixin:
    installment_vs_cash_calculate = graphene.Field(
        InstallmentVsCashCalculationPayloadType,
        cash_price=graphene.String(required=True),
        installment_count=graphene.Int(required=True),
        installment_amount=graphene.String(),
        installment_total=graphene.String(),
        first_payment_delay_days=graphene.Int(default_value=30),
        opportunity_rate_type=graphene.String(default_value="manual"),
        opportunity_rate_annual=graphene.String(),
        inflation_rate_annual=graphene.String(required=True),
        fees_enabled=graphene.Boolean(default_value=False),
        fees_upfront=graphene.String(default_value="0.00"),
        scenario_label=graphene.String(),
    )

    simulations = graphene.Field(
        SimulationListPayloadType,
        page=graphene.Int(default_value=1),
        per_page=graphene.Int(default_value=20),
        tool_id=graphene.String(),
        required=True,
    )

    simulation = graphene.Field(
        SimulationType,
        id=graphene.UUID(required=True),
    )

    simulation_quota = graphene.Field(SimulationQuotaType, required=True)

    def resolve_simulation_quota(
        self, _info: graphene.ResolveInfo
    ) -> SimulationQuotaType:
        from app.application.services import simulation_quota_service

        user = get_current_user_required()
        quota = simulation_quota_service.get_quota(UUID(str(user.id)))
        return _to_quota_type(dict(quota))

    def resolve_installment_vs_cash_calculate(
        self,
        _info: graphene.ResolveInfo,
        **kwargs: object,
    ) -> InstallmentVsCashCalculationPayloadType:
        service = InstallmentVsCashApplicationService.with_defaults(None)
        try:
            result = service.calculate(dict(kwargs))
        except InstallmentVsCashApplicationError as exc:
            raise_installment_vs_cash_graphql_error(exc)
        return to_installment_vs_cash_calculation_type(result)

    def resolve_simulations(
        self,
        _info: graphene.ResolveInfo,
        page: int = 1,
        per_page: int = 20,
        tool_id: str | None = None,
    ) -> SimulationListPayloadType:
        user = get_current_user_required()
        service = SimulationApplicationService.with_defaults(UUID(str(user.id)))
        try:
            result = service.list_simulations(
                page=page, per_page=per_page, tool_id=tool_id
            )
        except SimulationApplicationError as exc:
            _raise_simulation_graphql_error(exc)
        items = [_to_simulation_type(item) for item in result["items"]]
        pagination = result["pagination"]
        return SimulationListPayloadType(
            items=items,
            page=pagination["page"],
            per_page=pagination["per_page"],
            total=pagination["total"],
            pages=pagination["pages"],
        )

    def resolve_simulation(
        self,
        _info: graphene.ResolveInfo,
        id: UUID,
    ) -> SimulationType:
        user = get_current_user_required()
        service = SimulationApplicationService.with_defaults(UUID(str(user.id)))
        try:
            data = service.get_simulation(id)
        except SimulationApplicationError as exc:
            _raise_simulation_graphql_error(exc)
        return _to_simulation_type(data)
