"""Service de quota do simulador de metas (freemium) — #1409.

Free tier: ``FREE_MONTHLY_LIMIT`` simulações completas por mês (UTC). Premium
(entitlement ``advanced_simulations``) é ilimitado. O consumo nunca lança erro
por esgotamento — retorna ``allowed=False`` para o cliente decidir a UX (paywall).
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict, cast
from uuid import UUID

from app.extensions.database import db
from app.models.simulation_quota_usage import SimulationQuotaUsage
from app.services.entitlement_service import has_entitlement
from app.utils.datetime_utils import utc_now_naive

FREE_MONTHLY_LIMIT = 1
PREMIUM_FEATURE_KEY = "advanced_simulations"


class SimulationQuota(TypedDict):
    """Snapshot da quota retornado por get_quota/consume."""

    limit: int
    used: int
    remaining: int | None  # None quando unlimited
    unlimited: bool
    allowed: bool
    reset_at: str  # ISO UTC do próximo reset (1º dia do próximo mês 00:00)


def _current_period(now: datetime | None = None) -> str:
    return (now or utc_now_naive()).strftime("%Y-%m")


def _next_reset_at(now: datetime | None = None) -> str:
    ref = now or utc_now_naive()
    year = ref.year + (1 if ref.month == 12 else 0)
    month = 1 if ref.month == 12 else ref.month + 1
    return datetime(year, month, 1).isoformat() + "Z"


def _is_premium(user_id: str | UUID) -> bool:
    return has_entitlement(user_id, PREMIUM_FEATURE_KEY)


def _get_or_create_row(user_id: UUID, period: str) -> SimulationQuotaUsage:
    row = cast(
        "SimulationQuotaUsage | None",
        SimulationQuotaUsage.query.filter_by(
            user_id=user_id, period=period
        ).one_or_none(),
    )
    if row is None:
        row = SimulationQuotaUsage(user_id=user_id, period=period, count=0)
        db.session.add(row)
        db.session.flush()
    return row


def _unlimited_snapshot() -> SimulationQuota:
    return SimulationQuota(
        limit=FREE_MONTHLY_LIMIT,
        used=0,
        remaining=None,
        unlimited=True,
        allowed=True,
        reset_at=_next_reset_at(),
    )


def get_quota(user_id: str | UUID) -> SimulationQuota:
    """Snapshot da quota do usuário (sem consumir)."""
    normalized = UUID(str(user_id))
    if _is_premium(normalized):
        return _unlimited_snapshot()

    period = _current_period()
    row = SimulationQuotaUsage.query.filter_by(
        user_id=normalized, period=period
    ).one_or_none()
    used = row.count if row is not None else 0
    remaining = max(FREE_MONTHLY_LIMIT - used, 0)
    return SimulationQuota(
        limit=FREE_MONTHLY_LIMIT,
        used=used,
        remaining=remaining,
        unlimited=False,
        allowed=remaining > 0,
        reset_at=_next_reset_at(),
    )


def consume(user_id: str | UUID) -> SimulationQuota:
    """Consome 1 simulação se permitido. Não lança em esgotamento.

    - premium → no-op, retorna unlimited/allowed.
    - free com saldo → incrementa e retorna allowed=True.
    - free esgotado → retorna allowed=False sem incrementar.
    """
    normalized = UUID(str(user_id))
    if _is_premium(normalized):
        return _unlimited_snapshot()

    period = _current_period()
    row = _get_or_create_row(normalized, period)
    if row.count >= FREE_MONTHLY_LIMIT:
        db.session.commit()
        return SimulationQuota(
            limit=FREE_MONTHLY_LIMIT,
            used=row.count,
            remaining=0,
            unlimited=False,
            allowed=False,
            reset_at=_next_reset_at(),
        )

    row.count += 1
    db.session.commit()
    return SimulationQuota(
        limit=FREE_MONTHLY_LIMIT,
        used=row.count,
        remaining=max(FREE_MONTHLY_LIMIT - row.count, 0),
        unlimited=False,
        allowed=True,
        reset_at=_next_reset_at(),
    )
