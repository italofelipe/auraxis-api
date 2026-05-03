from __future__ import annotations

from typing import Any
from uuid import UUID

import graphene

from app.application.services.goal_application_service import (
    GoalApplicationError,
    GoalApplicationService,
)
from app.graphql.auth import get_current_user_required
from app.graphql.goal_presenters import (
    raise_goal_graphql_error,
    to_goal_plan_type,
    to_goal_type_object,
)
from app.graphql.observability import log_graphql_resolver
from app.graphql.types import GoalPlanType, GoalTypeObject


class CreateGoalMutation(graphene.Mutation):
    class Arguments:
        title = graphene.String(required=True)
        target_amount = graphene.String(required=True)
        current_amount = graphene.String()
        priority = graphene.Int()
        target_date = graphene.String()
        status = graphene.String()
        description = graphene.String()
        category = graphene.String()

    message = graphene.String(required=True)
    goal = graphene.Field(GoalTypeObject, required=True)

    def mutate(self, info: graphene.ResolveInfo, **kwargs: Any) -> "CreateGoalMutation":
        user = get_current_user_required()
        service = GoalApplicationService.with_defaults(UUID(str(user.id)))
        try:
            goal_data = service.create_goal(kwargs)
        except GoalApplicationError as exc:
            raise_goal_graphql_error(exc)
        return CreateGoalMutation(
            message="Meta criada com sucesso",
            goal=to_goal_type_object(goal_data),
        )


class UpdateGoalMutation(graphene.Mutation):
    class Arguments:
        goal_id = graphene.UUID(required=True)
        title = graphene.String()
        target_amount = graphene.String()
        current_amount = graphene.String()
        priority = graphene.Int()
        target_date = graphene.String()
        status = graphene.String()
        description = graphene.String()
        category = graphene.String()

    message = graphene.String(required=True)
    goal = graphene.Field(GoalTypeObject, required=True)

    def mutate(
        self, info: graphene.ResolveInfo, goal_id: UUID, **kwargs: Any
    ) -> "UpdateGoalMutation":
        user = get_current_user_required()
        service = GoalApplicationService.with_defaults(UUID(str(user.id)))
        try:
            goal_data = service.update_goal(goal_id, kwargs)
        except GoalApplicationError as exc:
            raise_goal_graphql_error(exc)
        return UpdateGoalMutation(
            message="Meta atualizada com sucesso",
            goal=to_goal_type_object(goal_data),
        )


class DeleteGoalMutation(graphene.Mutation):
    class Arguments:
        goal_id = graphene.UUID(required=True)

    ok = graphene.Boolean(required=True)
    message = graphene.String(required=True)

    @log_graphql_resolver("deleteGoal")
    def mutate(self, info: graphene.ResolveInfo, goal_id: UUID) -> "DeleteGoalMutation":
        user = get_current_user_required()
        service = GoalApplicationService.with_defaults(UUID(str(user.id)))
        try:
            service.delete_goal(goal_id)
        except GoalApplicationError as exc:
            raise_goal_graphql_error(exc)
        return DeleteGoalMutation(
            ok=True,
            message="Meta removida com sucesso",
        )


class SimulateGoalPlanMutation(graphene.Mutation):
    class Arguments:
        target_amount = graphene.String(required=True)
        current_amount = graphene.String()
        target_date = graphene.String()
        monthly_income = graphene.String()
        monthly_expenses = graphene.String()
        monthly_contribution = graphene.String()

    message = graphene.String(required=True)
    goal_plan = graphene.Field(GoalPlanType, required=True)

    def mutate(
        self, info: graphene.ResolveInfo, **kwargs: Any
    ) -> "SimulateGoalPlanMutation":
        user = get_current_user_required()
        service = GoalApplicationService.with_defaults(UUID(str(user.id)))
        try:
            result = service.simulate_goal_plan(kwargs)
        except GoalApplicationError as exc:
            raise_goal_graphql_error(exc)
        return SimulateGoalPlanMutation(
            message="Simulação da meta calculada com sucesso",
            goal_plan=to_goal_plan_type(result["goal_plan"]),
        )
