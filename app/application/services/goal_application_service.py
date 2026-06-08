from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, cast
from uuid import UUID

from marshmallow import ValidationError

from app.extensions.database import db
from app.models.goal_contribution import GoalContribution
from app.models.user import User
from app.schemas.goal_planning_schema import GoalSimulationSchema
from app.schemas.goal_schema import (
    GoalContributionInputSchema,
    GoalContributionSchema,
)
from app.services.goal_planning_service import GoalPlanningInput, GoalPlanningService
from app.services.goal_projection_service import GoalProjectionService
from app.services.goal_service import GoalService, GoalServiceError
from app.utils.datetime_utils import utc_now_naive

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoalApplicationError(Exception):
    message: str
    code: str
    status_code: int
    details: dict[str, Any] | None = None


class GoalApplicationService:
    def __init__(
        self,
        *,
        user_id: UUID,
        goal_service_factory: Callable[[UUID], GoalService],
        goal_planning_service_factory: Callable[[], GoalPlanningService],
        get_user_by_id: Callable[[UUID], User | None],
    ) -> None:
        self._user_id = user_id
        self._goal_service = goal_service_factory(user_id)
        self._goal_planning_service_factory = goal_planning_service_factory
        self._get_user_by_id = get_user_by_id
        self._simulation_schema = GoalSimulationSchema()
        self._contribution_input_schema = GoalContributionInputSchema()
        self._contribution_output_schema = GoalContributionSchema()

    @classmethod
    def with_defaults(cls, user_id: UUID) -> GoalApplicationService:
        return cls(
            user_id=user_id,
            goal_service_factory=GoalService,
            goal_planning_service_factory=GoalPlanningService,
            get_user_by_id=_default_get_user_by_id,
        )

    def create_goal(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            goal = self._goal_service.create_goal(payload)
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc
        return self._goal_service.serialize(goal)

    def list_goals(
        self,
        *,
        page: int,
        per_page: int,
        status: str | None,
    ) -> dict[str, Any]:
        try:
            goals, pagination = self._goal_service.list_goals(
                page=page,
                per_page=per_page,
                status=status,
            )
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc
        return {
            "items": [self._goal_service.serialize(goal) for goal in goals],
            "pagination": pagination,
        }

    def get_goal(self, goal_id: UUID) -> dict[str, Any]:
        try:
            goal = self._goal_service.get_goal(goal_id)
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc
        return self._goal_service.serialize(goal)

    def update_goal(self, goal_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        old_amount: Decimal | None = None
        if "current_amount" in payload:
            try:
                old_goal = self._goal_service.get_goal(goal_id)
                old_amount = Decimal(str(old_goal.current_amount or 0))
            except GoalServiceError:
                old_amount = None

        try:
            goal = self._goal_service.update_goal(goal_id, payload)
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc

        if old_amount is not None and "current_amount" in payload:
            new_amount = Decimal(str(goal.current_amount or 0))
            delta = new_amount - old_amount
            if delta != 0:
                _record_contribution(
                    goal_id=goal.id,
                    user_id=self._user_id,
                    delta=delta,
                )

        return self._goal_service.serialize(goal)

    def add_contribution(
        self, goal_id: UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Register a deposit (+) or withdrawal (-) against a goal.

        Applies the signed delta to ``current_amount``, records a
        ``GoalContribution`` history row and auto-completes the goal when the
        target is reached. Rejects withdrawals that would drive the balance
        negative.
        """
        try:
            validated = self._contribution_input_schema.load(payload)
        except ValidationError as exc:
            raise GoalApplicationError(
                message="Dados inválidos para a contribuição.",
                code="VALIDATION_ERROR",
                status_code=400,
                details={"messages": exc.messages},
            ) from exc

        try:
            goal = self._goal_service.get_goal(goal_id)
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc

        amount = Decimal(str(validated["amount"]))
        current = Decimal(str(goal.current_amount or 0))
        new_amount = current + amount
        if new_amount < 0:
            raise GoalApplicationError(
                message="A retirada excede o saldo acumulado da meta.",
                code="INSUFFICIENT_BALANCE",
                status_code=400,
            )

        goal.current_amount = new_amount
        target = Decimal(str(goal.target_amount or 0))
        if target > 0 and new_amount >= target and goal.status == "active":
            goal.status = "completed"

        occurred_at = validated.get("occurred_at") or utc_now_naive().date()
        contribution = GoalContribution(
            goal_id=goal.id,
            user_id=self._user_id,
            amount=amount,
            note=validated.get("note"),
            occurred_at=occurred_at,
        )
        db.session.add(contribution)
        db.session.commit()

        return {
            "goal": self._goal_service.serialize(goal),
            "contribution": self._contribution_output_schema.dump(contribution),
        }

    def list_contributions(
        self, goal_id: UUID, *, page: int, per_page: int
    ) -> dict[str, Any]:
        """Return the paginated contribution history for a goal (newest first)."""
        try:
            self._goal_service.get_goal(goal_id)
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc

        pagination = (
            GoalContribution.query.filter_by(goal_id=goal_id)
            .order_by(
                GoalContribution.occurred_at.desc(),
                GoalContribution.created_at.desc(),
            )
            .paginate(page=page, per_page=per_page, error_out=False)
        )
        return {
            "items": [
                self._contribution_output_schema.dump(item) for item in pagination.items
            ],
            "pagination": {
                "total": int(pagination.total),
                "page": int(pagination.page),
                "per_page": int(pagination.per_page),
                "pages": int(pagination.pages),
            },
        }

    def delete_goal(self, goal_id: UUID) -> None:
        try:
            self._goal_service.delete_goal(goal_id)
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc

    def get_goal_plan(self, goal_id: UUID) -> dict[str, Any]:
        try:
            goal = self._goal_service.get_goal(goal_id)
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc

        user = self._get_user_by_id(self._user_id)
        if user is None:
            raise GoalApplicationError(
                message="Usuário não encontrado.",
                code="NOT_FOUND",
                status_code=404,
            )

        planning_service = self._goal_planning_service_factory()
        planning_input = GoalPlanningInput(
            target_amount=goal.target_amount,
            current_amount=goal.current_amount,
            target_date=goal.target_date,
            monthly_income=user.monthly_income,
            monthly_expenses=user.monthly_expenses,
            monthly_contribution=user.monthly_investment,
        )
        return {
            "goal": self._goal_service.serialize(goal),
            "goal_plan": planning_service.serialize_plan(
                planning_service.build_plan(planning_input)
            ),
        }

    def get_goal_projection(self, goal_id: UUID) -> dict[str, Any]:
        try:
            goal = self._goal_service.get_goal(goal_id)
        except GoalServiceError as exc:
            raise _to_goal_application_error(exc) from exc

        user = self._get_user_by_id(self._user_id)
        monthly_contribution = (
            Decimal(str(user.monthly_investment))
            if user is not None and user.monthly_investment is not None
            else Decimal("0")
        )

        projection_service = GoalProjectionService(
            monthly_contribution=monthly_contribution,
        )
        projection = projection_service.project(
            goal_id=goal.id,
            user_id=self._user_id,
            current_amount=goal.current_amount,
            target_amount=goal.target_amount,
            target_date=goal.target_date,
        )
        return {
            "goal": self._goal_service.serialize(goal),
            "projection": projection_service.serialize(projection),
        }

    def simulate_goal_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            validated = self._simulation_schema.load(payload)
        except ValidationError as exc:
            raise GoalApplicationError(
                message="Dados inválidos para simulação de meta.",
                code="VALIDATION_ERROR",
                status_code=400,
                details={"messages": exc.messages},
            ) from exc

        planning_service = self._goal_planning_service_factory()
        planning_input = GoalPlanningInput(
            target_amount=validated["target_amount"],
            current_amount=validated["current_amount"],
            target_date=validated.get("target_date"),
            monthly_income=validated.get("monthly_income"),
            monthly_expenses=validated.get("monthly_expenses"),
            monthly_contribution=validated.get("monthly_contribution"),
        )
        return {
            "goal_plan": planning_service.serialize_plan(
                planning_service.build_plan(planning_input)
            )
        }


def _to_goal_application_error(exc: GoalServiceError) -> GoalApplicationError:
    return GoalApplicationError(
        message=exc.message,
        code=exc.code,
        status_code=exc.status_code,
        details=exc.details,
    )


def _default_get_user_by_id(user_id: UUID) -> User | None:
    return cast(User | None, User.query.filter_by(id=user_id).first())


def _record_contribution(*, goal_id: UUID, user_id: UUID, delta: Decimal) -> None:
    """Persist a GoalContribution row. Swallows exceptions so that tracking
    failures never break the goal update flow."""
    try:
        contribution = GoalContribution(
            goal_id=goal_id,
            user_id=user_id,
            amount=delta,
        )
        db.session.add(contribution)
        db.session.commit()
    except Exception as exc:
        log.warning(
            "goal_contribution.record_failed goal_id=%s user_id=%s error=%s",
            goal_id,
            user_id,
            exc,
        )
        db.session.rollback()
