from __future__ import annotations

from collections.abc import Mapping

from app.application.services.goal_application_service import GoalApplicationError
from app.graphql.errors import (
    GRAPHQL_ERROR_CODE_FORBIDDEN,
    GRAPHQL_ERROR_CODE_NOT_FOUND,
    GRAPHQL_ERROR_CODE_VALIDATION,
    build_public_graphql_error,
)
from app.graphql.types import (
    GoalContributionType,
    GoalPlanType,
    GoalRecommendationType,
    GoalTypeObject,
)

_GOAL_GRAPHQL_FIELDS = {
    "id",
    "title",
    "description",
    "category",
    "target_amount",
    "current_amount",
    "priority",
    "target_date",
    "status",
    "created_at",
    "updated_at",
}
_GOAL_CONTRIBUTION_GRAPHQL_FIELDS = {
    "id",
    "goal_id",
    "amount",
    "note",
    "occurred_at",
    "created_at",
}
_GOAL_ERROR_CODE_MAP = {
    "VALIDATION_ERROR": GRAPHQL_ERROR_CODE_VALIDATION,
    "NOT_FOUND": GRAPHQL_ERROR_CODE_NOT_FOUND,
    "FORBIDDEN": GRAPHQL_ERROR_CODE_FORBIDDEN,
    "INSUFFICIENT_BALANCE": GRAPHQL_ERROR_CODE_VALIDATION,
}


def raise_goal_graphql_error(exc: GoalApplicationError) -> None:
    graphql_code = _GOAL_ERROR_CODE_MAP.get(exc.code, GRAPHQL_ERROR_CODE_VALIDATION)
    raise build_public_graphql_error(exc.message, code=graphql_code) from exc


def to_goal_type_object(goal_data: Mapping[str, object]) -> GoalTypeObject:
    filtered = {
        key: value for key, value in goal_data.items() if key in _GOAL_GRAPHQL_FIELDS
    }
    return GoalTypeObject(**filtered)


def to_goal_contribution_type(
    contribution_data: Mapping[str, object],
) -> GoalContributionType:
    filtered = {
        key: value
        for key, value in contribution_data.items()
        if key in _GOAL_CONTRIBUTION_GRAPHQL_FIELDS
    }
    return GoalContributionType(**filtered)


def to_goal_plan_type(plan_data: Mapping[str, object]) -> GoalPlanType:
    raw_recommendations = plan_data.get("recommendations", [])
    recommendations: list[GoalRecommendationType] = []
    if isinstance(raw_recommendations, list):
        recommendations = [
            GoalRecommendationType(**item)
            for item in raw_recommendations
            if isinstance(item, dict)
        ]
    payload = dict(plan_data)
    payload["recommendations"] = recommendations
    return GoalPlanType(**payload)
