from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import SupportsFloat, cast
from uuid import UUID

from app.models.user import User
from app.models.wallet import Wallet


@dataclass(frozen=True)
class AuthenticatedUserProfile:
    id: str
    name: str
    email: str
    gender: str | None
    birth_date: str | None
    monthly_income: float | None
    monthly_income_net: float | None
    net_worth: float | None
    monthly_expenses: float | None
    initial_investment: float | None
    monthly_investment: float | None
    investment_goal_date: str | None
    state_uf: str | None
    occupation: str | None
    investor_profile: str | None
    financial_objectives: str | None
    investor_profile_suggested: str | None
    profile_quiz_score: int | None
    taxonomy_version: str | None
    entitlements_version: int
    avatar_url: str | None
    # Onboarding completion timestamp (ISO 8601) or None (#1471)
    onboarding_completed_at: str | None = None
    # Email verification status (14d grace period soft-block)
    email_verified: bool = False
    email_verification_deadline_at: str | None = None
    email_verification_required_now: bool = False
    days_until_email_required: int | None = None


@dataclass(frozen=True)
class AuthenticatedWalletEntry:
    id: str
    name: str
    value: float | None
    estimated_value_on_create_date: float | None
    ticker: str | None
    quantity: int | None
    asset_class: str
    annual_rate: float | None
    target_withdraw_date: str | None
    register_date: str
    should_be_on_wallet: bool


@dataclass(frozen=True)
class AuthenticatedUserContext:
    profile: AuthenticatedUserProfile
    wallet_entries: tuple[AuthenticatedWalletEntry, ...]


@dataclass(frozen=True)
class AuthenticatedUserContextDependencies:
    list_wallet_entries_by_user_id: Callable[[UUID], Sequence[Wallet]]


def _to_float_or_none(value: SupportsFloat | None) -> float | None:
    return float(value) if value is not None else None


def _isoformat_or_none(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _default_list_wallet_entries_by_user_id(user_id: UUID) -> Sequence[Wallet]:
    return cast(Sequence[Wallet], Wallet.query.filter_by(user_id=user_id).all())


def _default_dependencies() -> AuthenticatedUserContextDependencies:
    return AuthenticatedUserContextDependencies(
        list_wallet_entries_by_user_id=_default_list_wallet_entries_by_user_id,
    )


class AuthenticatedUserContextService:
    def __init__(
        self,
        *,
        dependencies: AuthenticatedUserContextDependencies,
    ) -> None:
        self._dependencies = dependencies

    @classmethod
    def with_defaults(cls) -> AuthenticatedUserContextService:
        return cls(dependencies=_default_dependencies())

    def build_profile(self, user: User) -> AuthenticatedUserProfile:
        monthly_income = _to_float_or_none(user.monthly_income_net)
        return AuthenticatedUserProfile(
            id=str(user.id),
            name=user.name,
            email=user.email,
            gender=user.gender,
            birth_date=_isoformat_or_none(user.birth_date),
            monthly_income=monthly_income,
            monthly_income_net=monthly_income,
            net_worth=_to_float_or_none(user.net_worth),
            monthly_expenses=_to_float_or_none(user.monthly_expenses),
            initial_investment=_to_float_or_none(user.initial_investment),
            monthly_investment=_to_float_or_none(user.monthly_investment),
            investment_goal_date=_isoformat_or_none(user.investment_goal_date),
            state_uf=user.state_uf,
            occupation=user.occupation,
            investor_profile=user.investor_profile,
            financial_objectives=user.financial_objectives,
            investor_profile_suggested=user.investor_profile_suggested,
            profile_quiz_score=user.profile_quiz_score,
            taxonomy_version=user.taxonomy_version,
            entitlements_version=int(user.entitlements_version or 0),
            avatar_url=user.avatar_url,
            onboarding_completed_at=_datetime_isoformat_or_none(
                user.onboarding_completed_at
            ),
            email_verified=bool(user.email_verified),
            email_verification_deadline_at=_datetime_isoformat_or_none(
                user.email_verification_deadline_at
            ),
            email_verification_required_now=bool(user.email_verification_required_now),
            days_until_email_required=user.days_until_email_required,
        )

    def build_wallet_entries(
        self, user_id: UUID
    ) -> tuple[AuthenticatedWalletEntry, ...]:
        wallet_entries = self._dependencies.list_wallet_entries_by_user_id(user_id)
        return self.build_wallet_entries_snapshot(wallet_entries)

    def build_wallet_entries_snapshot(
        self,
        wallet_entries: Sequence[Wallet],
    ) -> tuple[AuthenticatedWalletEntry, ...]:
        return tuple(self._build_wallet_entry(entry) for entry in wallet_entries)

    def build_context(self, user: User) -> AuthenticatedUserContext:
        return AuthenticatedUserContext(
            profile=self.build_profile(user),
            wallet_entries=self.build_wallet_entries(user.id),
        )

    def _build_wallet_entry(self, wallet: Wallet) -> AuthenticatedWalletEntry:
        return AuthenticatedWalletEntry(
            id=str(wallet.id),
            name=wallet.name,
            value=_to_float_or_none(wallet.value),
            estimated_value_on_create_date=_to_float_or_none(
                wallet.estimated_value_on_create_date
            ),
            ticker=wallet.ticker,
            quantity=wallet.quantity,
            asset_class=wallet.asset_class,
            annual_rate=_to_float_or_none(wallet.annual_rate),
            target_withdraw_date=_isoformat_or_none(wallet.target_withdraw_date),
            register_date=wallet.register_date.isoformat(),
            should_be_on_wallet=wallet.should_be_on_wallet,
        )


__all__ = [
    "AuthenticatedUserContext",
    "AuthenticatedUserContextDependencies",
    "AuthenticatedUserContextService",
    "AuthenticatedUserProfile",
    "AuthenticatedWalletEntry",
]
