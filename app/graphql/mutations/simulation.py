from __future__ import annotations

from uuid import UUID

import graphene

from app.application.services.installment_vs_cash_application_service import (
    InstallmentVsCashApplicationError,
    InstallmentVsCashApplicationService,
)
from app.graphql.auth import get_current_user_required
from app.graphql.errors import GRAPHQL_ERROR_CODE_FORBIDDEN, build_public_graphql_error
from app.graphql.goal_presenters import to_goal_type_object
from app.graphql.installment_vs_cash_presenters import (
    raise_installment_vs_cash_graphql_error,
    to_installment_vs_cash_calculation_type,
    to_installment_vs_cash_simulation_type,
)
from app.graphql.types import TransactionTypeObject
from app.services.entitlement_service import has_entitlement

INSTALLMENT_VS_CASH_SIMULATION_TYPE = (
    "app.graphql.types.InstallmentVsCashSimulationType"
)


def _require_advanced_simulations(user_id: UUID) -> None:
    if has_entitlement(user_id, "advanced_simulations"):
        return
    raise build_public_graphql_error(
        "Feature 'advanced_simulations' requires an active entitlement.",
        code=GRAPHQL_ERROR_CODE_FORBIDDEN,
    )


class SaveInstallmentVsCashSimulationMutation(graphene.Mutation):
    class Arguments:
        cash_price = graphene.String(required=True)
        installment_count = graphene.Int(required=True)
        installment_amount = graphene.String()
        installment_total = graphene.String()
        first_payment_delay_days = graphene.Int(default_value=30)
        opportunity_rate_type = graphene.String(default_value="manual")
        opportunity_rate_annual = graphene.String()
        inflation_rate_annual = graphene.String(required=True)
        fees_enabled = graphene.Boolean(default_value=False)
        fees_upfront = graphene.String(default_value="0.00")
        scenario_label = graphene.String()

    message = graphene.String(required=True)
    simulation = graphene.Field(
        INSTALLMENT_VS_CASH_SIMULATION_TYPE,
        required=True,
    )
    calculation = graphene.Field(
        "app.graphql.types.InstallmentVsCashCalculationPayloadType",
        required=True,
    )

    def mutate(
        self,
        _info: graphene.ResolveInfo,
        **kwargs: object,
    ) -> "SaveInstallmentVsCashSimulationMutation":
        user = get_current_user_required()
        service = InstallmentVsCashApplicationService.with_defaults(UUID(str(user.id)))
        try:
            result = service.save_simulation(dict(kwargs))
        except InstallmentVsCashApplicationError as exc:
            raise_installment_vs_cash_graphql_error(exc)
        return SaveInstallmentVsCashSimulationMutation(
            message="Simulação salva com sucesso",
            simulation=to_installment_vs_cash_simulation_type(result["simulation"]),
            calculation=to_installment_vs_cash_calculation_type(result["calculation"]),
        )


class CreateGoalFromInstallmentVsCashSimulationMutation(graphene.Mutation):
    class Arguments:
        simulation_id = graphene.UUID(required=True)
        title = graphene.String(required=True)
        selected_option = graphene.String(required=True)
        current_amount = graphene.String(default_value="0.00")
        priority = graphene.Int(default_value=3)
        description = graphene.String()
        category = graphene.String(default_value="planned_purchase")
        target_date = graphene.String()

    message = graphene.String(required=True)
    goal = graphene.Field("app.graphql.types.GoalTypeObject", required=True)
    simulation = graphene.Field(
        INSTALLMENT_VS_CASH_SIMULATION_TYPE,
        required=True,
    )

    def mutate(
        self,
        _info: graphene.ResolveInfo,
        simulation_id: UUID,
        **kwargs: object,
    ) -> "CreateGoalFromInstallmentVsCashSimulationMutation":
        user = get_current_user_required()
        user_id = UUID(str(user.id))
        _require_advanced_simulations(user_id)
        service = InstallmentVsCashApplicationService.with_defaults(user_id)
        try:
            result = service.create_goal_from_simulation(simulation_id, dict(kwargs))
        except InstallmentVsCashApplicationError as exc:
            raise_installment_vs_cash_graphql_error(exc)
        return CreateGoalFromInstallmentVsCashSimulationMutation(
            message="Meta criada com sucesso a partir da simulação",
            goal=to_goal_type_object(result["goal"]),
            simulation=to_installment_vs_cash_simulation_type(result["simulation"]),
        )


class CreatePlannedExpenseFromInstallmentVsCashSimulationMutation(graphene.Mutation):
    class Arguments:
        simulation_id = graphene.UUID(required=True)
        title = graphene.String(required=True)
        selected_option = graphene.String(required=True)
        description = graphene.String()
        observation = graphene.String()
        due_date = graphene.String()
        first_due_date = graphene.String()
        upfront_due_date = graphene.String()
        tag_id = graphene.UUID()
        account_id = graphene.UUID()
        credit_card_id = graphene.UUID()
        currency = graphene.String(default_value="BRL")
        status = graphene.String(default_value="pending")

    message = graphene.String(required=True)
    transactions = graphene.List(TransactionTypeObject, required=True)
    simulation = graphene.Field(
        INSTALLMENT_VS_CASH_SIMULATION_TYPE,
        required=True,
    )

    def mutate(
        self,
        _info: graphene.ResolveInfo,
        simulation_id: UUID,
        **kwargs: object,
    ) -> "CreatePlannedExpenseFromInstallmentVsCashSimulationMutation":
        user = get_current_user_required()
        user_id = UUID(str(user.id))
        _require_advanced_simulations(user_id)
        service = InstallmentVsCashApplicationService.with_defaults(user_id)
        try:
            result = service.create_planned_expense_from_simulation(
                simulation_id,
                dict(kwargs),
            )
        except InstallmentVsCashApplicationError as exc:
            raise_installment_vs_cash_graphql_error(exc)
        return CreatePlannedExpenseFromInstallmentVsCashSimulationMutation(
            message="Despesa planejada criada com sucesso a partir da simulação",
            transactions=[
                TransactionTypeObject(**item) for item in result["transactions"]
            ],
            simulation=to_installment_vs_cash_simulation_type(result["simulation"]),
        )


class ConsumeSimulationQuotaMutation(graphene.Mutation):
    """Consome 1 simulação da quota freemium (#1409).

    Parity de ``POST /simulations/quota/consume``. Não falha em esgotamento:
    retorna ``quota.allowed=False`` para o cliente exibir o paywall.
    """

    quota = graphene.Field(
        "app.graphql.queries.simulation.SimulationQuotaType", required=True
    )

    def mutate(self, _info: graphene.ResolveInfo) -> "ConsumeSimulationQuotaMutation":
        from app.application.services import simulation_quota_service
        from app.graphql.queries.simulation import _to_quota_type

        user = get_current_user_required()
        quota = simulation_quota_service.consume(UUID(str(user.id)))
        return ConsumeSimulationQuotaMutation(quota=_to_quota_type(dict(quota)))
