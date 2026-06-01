# mypy: disable-error-code="name-defined"
"""SimulationQuotaUsage model — freemium quota do simulador de metas (#1409).

Conta quantas simulações completas um usuário free executou no mês corrente.
O reset mensal é implícito: cada período (``YYYY-MM`` em UTC) tem sua própria
linha, então virar o mês cria um novo contador zerado. Premium (entitlement
``advanced_simulations``) ignora a tabela e é tratado como ilimitado no service.
"""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import UUID

from app.extensions.database import db
from app.utils.datetime_utils import utc_now_naive


class SimulationQuotaUsage(db.Model):
    """Contador mensal de simulações completas por usuário (free tier)."""

    __tablename__ = "simulation_quota_usage"

    id = db.Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False
    )
    user_id = db.Column(
        UUID(as_uuid=True), db.ForeignKey("users.id"), nullable=False, index=True
    )
    # Período de cobrança no formato ``YYYY-MM`` calculado em UTC.
    period = db.Column(db.String(7), nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now_naive)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "period", name="uq_simulation_quota_user_period"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SimulationQuotaUsage user={self.user_id} period={self.period}"
            f" count={self.count}>"
        )
