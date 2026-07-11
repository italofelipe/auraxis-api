"""Investor profile targets and allocation diagnosis (MVP-3 wallet insights).

The product asks the LLM to comment on whether the user's actual portfolio
allocation matches their declared investor profile (``user.investor_profile``).
This module owns the canonical BR-market targets used as a baseline.

Canonical targets (decision 2026-05-18, see issue #1243)
--------------------------------------------------------
- ``conservador``: 70% renda_fixa / 30% renda_variavel, tolerance ±10pp
- ``moderado``  : 50% / 50%, tolerance ±15pp
- ``agressivo`` : 30% renda_fixa / 70% renda_variavel, tolerance ±15pp

These thresholds are intentionally conservative defaults; per-user overrides
are tracked as a separate follow-up (no SLA yet).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Callable, Iterable, Literal

from app.schemas.wallet_schema import (
    FIXED_INCOME_ASSET_CLASSES,
    MARKET_ASSET_CLASSES,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.wallet import Wallet


ProfileKey = Literal["conservador", "moderado", "agressivo"]
AlertLevel = Literal["aligned", "drift_warn", "drift_critical"]


@dataclass(frozen=True)
class ProfileTarget:
    """Canonical target for an investor profile."""

    profile: ProfileKey
    target_fixed_income_pct: Decimal
    target_market_pct: Decimal
    tolerance_pp: Decimal


PROFILE_TARGETS: dict[ProfileKey, ProfileTarget] = {
    "conservador": ProfileTarget(
        profile="conservador",
        target_fixed_income_pct=Decimal("70"),
        target_market_pct=Decimal("30"),
        tolerance_pp=Decimal("10"),
    ),
    "moderado": ProfileTarget(
        profile="moderado",
        target_fixed_income_pct=Decimal("50"),
        target_market_pct=Decimal("50"),
        tolerance_pp=Decimal("15"),
    ),
    "agressivo": ProfileTarget(
        profile="agressivo",
        target_fixed_income_pct=Decimal("30"),
        target_market_pct=Decimal("70"),
        tolerance_pp=Decimal("15"),
    ),
}


@dataclass(frozen=True)
class AllocationDistribution:
    """Snapshot of how the user's portfolio is split (in %)."""

    fixed_income_pct: Decimal
    market_pct: Decimal
    custom_pct: Decimal
    total_value: Decimal


@dataclass(frozen=True)
class AllocationDiagnosis:
    """Result of comparing actual allocation vs declared profile target."""

    profile: ProfileKey | None
    target: ProfileTarget | None
    distribution: AllocationDistribution
    alert_level: AlertLevel
    drift_pp: Decimal | None
    notes: tuple[str, ...]


def compute_distribution(
    wallets: Iterable["Wallet"],
    *,
    value_resolver: Callable[["Wallet"], Decimal] | None = None,
) -> AllocationDistribution:
    """Return percent split of a wallet collection by asset-class bucket.

    ``value_resolver`` lets callers supply real (market) valuations per
    holding — e.g. from ``PortfolioValuationService`` — instead of the raw
    nullable ``Wallet.value`` column, which is NULL for ticker holdings and
    used to collapse the distribution to zero (#1546).
    """
    total = Decimal("0")
    fixed = Decimal("0")
    market = Decimal("0")
    custom = Decimal("0")
    for w in wallets:
        value = value_resolver(w) if value_resolver is not None else _wallet_value(w)
        if value <= 0:
            continue
        total += value
        asset = (w.asset_class or "custom").lower()
        if asset in FIXED_INCOME_ASSET_CLASSES:
            fixed += value
        elif asset in MARKET_ASSET_CLASSES:
            market += value
        else:
            custom += value

    if total == 0:
        return AllocationDistribution(
            fixed_income_pct=Decimal("0"),
            market_pct=Decimal("0"),
            custom_pct=Decimal("0"),
            total_value=Decimal("0"),
        )
    return AllocationDistribution(
        fixed_income_pct=(fixed / total * Decimal("100")).quantize(Decimal("0.01")),
        market_pct=(market / total * Decimal("100")).quantize(Decimal("0.01")),
        custom_pct=(custom / total * Decimal("100")).quantize(Decimal("0.01")),
        total_value=total,
    )


def evaluate_allocation(
    *,
    investor_profile: str | None,
    wallets: Iterable["Wallet"],
    value_resolver: Callable[["Wallet"], Decimal] | None = None,
) -> AllocationDiagnosis:
    """Diagnose whether the actual allocation matches the declared profile.

    When ``investor_profile`` is missing or unknown, the diagnosis is still
    produced (with ``profile=None``) so the LLM can surface the current
    distribution without an alignment claim.
    """
    distribution = compute_distribution(wallets, value_resolver=value_resolver)
    notes: list[str] = []
    profile_key = _normalize_profile(investor_profile)

    if profile_key is None:
        if investor_profile:
            notes.append(
                f"investor_profile='{investor_profile}' fora do conjunto canônico"
            )
        return AllocationDiagnosis(
            profile=None,
            target=None,
            distribution=distribution,
            alert_level="aligned",
            drift_pp=None,
            notes=tuple(notes),
        )

    target = PROFILE_TARGETS[profile_key]
    drift = abs(distribution.fixed_income_pct - target.target_fixed_income_pct)

    if drift <= target.tolerance_pp:
        alert_level: AlertLevel = "aligned"
    elif drift <= target.tolerance_pp * Decimal("2"):
        alert_level = "drift_warn"
    else:
        alert_level = "drift_critical"

    if distribution.custom_pct > Decimal("10"):
        notes.append("Alocação 'custom' acima de 10%; revisar classificação dos ativos")

    return AllocationDiagnosis(
        profile=profile_key,
        target=target,
        distribution=distribution,
        alert_level=alert_level,
        drift_pp=drift.quantize(Decimal("0.01")),
        notes=tuple(notes),
    )


def _normalize_profile(raw: str | None) -> ProfileKey | None:
    if not raw:
        return None
    normalized = raw.strip().lower()
    for key in PROFILE_TARGETS:
        if normalized == key:
            return key
    return None


def _wallet_value(wallet: "Wallet") -> Decimal:
    raw = wallet.value
    if raw is None:
        return Decimal("0")
    try:
        return Decimal(str(raw))
    except Exception:  # pragma: no cover — defensive
        return Decimal("0")


__all__ = [
    "AllocationDiagnosis",
    "AllocationDistribution",
    "AlertLevel",
    "PROFILE_TARGETS",
    "ProfileKey",
    "ProfileTarget",
    "compute_distribution",
    "evaluate_allocation",
]
