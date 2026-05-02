from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from marshmallow import ValidationError

from app.extensions.database import db
from app.models.goal import Goal
from app.schemas.goal_schema import GOAL_STATUSES, GoalSchema


@dataclass
class GoalServiceError(Exception):
    message: str
    code: str
    status_code: int
    details: dict[str, Any] | None = None


class GoalService:
    def __init__(self, user_id: UUID) -> None:
        self.user_id = user_id
        self._schema = GoalSchema()
        self._partial_schema = GoalSchema(partial=True)

    def create_goal(self, payload: dict[str, Any]) -> Goal:
        try:
            validated = self._schema.load(payload)
        except ValidationError as exc:
            raise GoalServiceError(
                message="Dados inválidos para meta.",
                code="VALIDATION_ERROR",
                status_code=400,
                details={"messages": exc.messages},
            ) from exc

        goal = Goal(user_id=self.user_id, **validated)
        db.session.add(goal)
        db.session.commit()
        return goal

    def list_goals(
        self,
        *,
        page: int,
        per_page: int,
        status: str | None = None,
    ) -> tuple[list[Goal], dict[str, int]]:
        query = Goal.query.filter_by(user_id=self.user_id)
        if status:
            normalized = status.strip().lower()
            if normalized not in GOAL_STATUSES:
                raise GoalServiceError(
                    message="Status de meta inválido.",
                    code="VALIDATION_ERROR",
                    status_code=400,
                )
            query = query.filter(Goal.status == normalized)

        pagination = query.order_by(
            Goal.priority.asc(), Goal.created_at.desc()
        ).paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )
        return cast(list[Goal], pagination.items), {
            "total": int(pagination.total),
            "page": int(pagination.page),
            "per_page": int(pagination.per_page),
            "pages": int(pagination.pages),
        }

    def get_goal(self, goal_id: UUID) -> Goal:
        goal = cast(Goal | None, Goal.query.filter_by(id=goal_id).first())
        if goal is None:
            raise GoalServiceError(
                message="Meta não encontrada.",
                code="NOT_FOUND",
                status_code=404,
            )
        if str(goal.user_id) != str(self.user_id):
            raise GoalServiceError(
                message="Você não tem permissão para acessar esta meta.",
                code="FORBIDDEN",
                status_code=403,
            )
        return goal

    def update_goal(self, goal_id: UUID, payload: dict[str, Any]) -> Goal:
        goal = self.get_goal(goal_id)
        try:
            validated = self._partial_schema.load(payload, partial=True)
        except ValidationError as exc:
            raise GoalServiceError(
                message="Dados inválidos para atualização da meta.",
                code="VALIDATION_ERROR",
                status_code=400,
                details={"messages": exc.messages},
            ) from exc

        for field, value in validated.items():
            setattr(goal, field, value)
        db.session.commit()
        return goal

    def delete_goal(self, goal_id: UUID) -> None:
        from app.extensions.audit_trail import record_entity_delete

        goal = self.get_goal(goal_id)
        db.session.delete(goal)
        record_entity_delete(
            entity_type="goal",
            entity_id=str(goal_id),
            actor_id=str(self.user_id),
        )
        db.session.commit()

    def serialize(self, goal: Goal) -> dict[str, Any]:
        return cast(dict[str, Any], self._schema.dump(goal))
