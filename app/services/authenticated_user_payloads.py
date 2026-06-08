from __future__ import annotations

from dataclasses import asdict
from typing import TypedDict, cast

from app.application.services.authenticated_user_bootstrap_service import (
    AuthenticatedUserBootstrap,
    AuthenticatedUserTransactionsPreview,
    AuthenticatedUserWalletPreview,
)
from app.application.services.authenticated_user_context_service import (
    AuthenticatedUserProfile,
    AuthenticatedWalletEntry,
)
from app.services.transaction_serialization import TransactionPayload


class UserProfilePayload(TypedDict):
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
    avatar_url: str | None
    onboarding_completed_at: str | None


class AuthenticatedUserIdentityPayload(TypedDict):
    id: str
    name: str
    email: str


class AuthenticatedUserProfileDetailsPayload(TypedDict):
    gender: str | None
    birth_date: str | None
    state_uf: str | None
    occupation: str | None


class AuthenticatedUserFinancialProfilePayload(TypedDict):
    monthly_income_net: float | None
    monthly_expenses: float | None
    net_worth: float | None
    initial_investment: float | None
    monthly_investment: float | None
    investment_goal_date: str | None


class AuthenticatedUserInvestorProfilePayload(TypedDict):
    declared: str | None
    suggested: str | None
    quiz_score: int | None
    taxonomy_version: str | None
    financial_objectives: str | None


class AuthenticatedUserProductContextPayload(TypedDict):
    entitlements_version: int
    onboarding_completed_at: str | None


class AuthenticatedUserEmailVerificationPayload(TypedDict):
    verified: bool
    deadline_at: str | None
    required_now: bool
    days_remaining: int | None


class AuthenticatedUserCanonicalPayload(TypedDict):
    identity: AuthenticatedUserIdentityPayload
    profile: AuthenticatedUserProfileDetailsPayload
    financial_profile: AuthenticatedUserFinancialProfilePayload
    investor_profile: AuthenticatedUserInvestorProfilePayload
    product_context: AuthenticatedUserProductContextPayload
    email_verification: AuthenticatedUserEmailVerificationPayload


class AuthenticatedUserTransactionsPreviewPayload(TypedDict):
    items: list[TransactionPayload]
    returned_items: int
    limit: int
    has_more: bool


class AuthenticatedUserBootstrapWalletPayload(TypedDict):
    items: list[WalletEntryPayload]
    total: int
    returned_items: int
    limit: int
    has_more: bool


class AuthenticatedUserBootstrapPayload(TypedDict):
    user: AuthenticatedUserCanonicalPayload
    transactions_preview: AuthenticatedUserTransactionsPreviewPayload
    wallet: AuthenticatedUserBootstrapWalletPayload


class WalletEntryPayload(TypedDict):
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


def to_user_profile_payload(profile: AuthenticatedUserProfile) -> UserProfilePayload:
    """Build the legacy v2 flat user payload.

    The v2 contract excludes the email-verification fields (clients read
    those from a separate header/endpoint; v3 surfaces them in the canonical
    ``email_verification`` block). ``onboarding_completed_at`` is exposed here
    too as an additive, backward-compatible field so the v2 web client can
    decide whether to show onboarding without migrating to v3 (#1471).
    """
    payload = asdict(profile)
    payload.pop("entitlements_version", None)
    payload.pop("email_verified", None)
    payload.pop("email_verification_deadline_at", None)
    payload.pop("email_verification_required_now", None)
    payload.pop("days_until_email_required", None)
    return cast(UserProfilePayload, payload)


def to_authenticated_user_canonical_payload(
    profile: AuthenticatedUserProfile,
) -> AuthenticatedUserCanonicalPayload:
    return {
        "identity": {
            "id": profile.id,
            "name": profile.name,
            "email": profile.email,
        },
        "profile": {
            "gender": profile.gender,
            "birth_date": profile.birth_date,
            "state_uf": profile.state_uf,
            "occupation": profile.occupation,
        },
        "financial_profile": {
            "monthly_income_net": profile.monthly_income_net,
            "monthly_expenses": profile.monthly_expenses,
            "net_worth": profile.net_worth,
            "initial_investment": profile.initial_investment,
            "monthly_investment": profile.monthly_investment,
            "investment_goal_date": profile.investment_goal_date,
        },
        "investor_profile": {
            "declared": profile.investor_profile,
            "suggested": profile.investor_profile_suggested,
            "quiz_score": profile.profile_quiz_score,
            "taxonomy_version": profile.taxonomy_version,
            "financial_objectives": profile.financial_objectives,
        },
        "product_context": {
            "entitlements_version": profile.entitlements_version,
            "onboarding_completed_at": profile.onboarding_completed_at,
        },
        "email_verification": {
            "verified": profile.email_verified,
            "deadline_at": profile.email_verification_deadline_at,
            "required_now": profile.email_verification_required_now,
            "days_remaining": profile.days_until_email_required,
        },
    }


def to_transactions_preview_payload(
    preview: AuthenticatedUserTransactionsPreview,
) -> AuthenticatedUserTransactionsPreviewPayload:
    return {
        "items": list(preview.items),
        "returned_items": preview.returned_items,
        "limit": preview.limit,
        "has_more": preview.has_more,
    }


def to_authenticated_user_bootstrap_payload(
    bootstrap: AuthenticatedUserBootstrap,
) -> AuthenticatedUserBootstrapPayload:
    wallet_preview = to_wallet_preview_payload(bootstrap.wallet_preview)
    return {
        "user": to_authenticated_user_canonical_payload(bootstrap.profile),
        "transactions_preview": to_transactions_preview_payload(
            bootstrap.transactions_preview
        ),
        "wallet": wallet_preview,
    }


def to_wallet_preview_payload(
    preview: AuthenticatedUserWalletPreview,
) -> AuthenticatedUserBootstrapWalletPayload:
    wallet_items = to_wallet_payload(preview.items)
    return {
        "items": wallet_items,
        "total": preview.total,
        "returned_items": preview.returned_items,
        "limit": preview.limit,
        "has_more": preview.has_more,
    }


def to_wallet_entry_payload(
    wallet_entry: AuthenticatedWalletEntry,
) -> WalletEntryPayload:
    return cast(WalletEntryPayload, asdict(wallet_entry))


def to_wallet_payload(
    wallet_entries: tuple[AuthenticatedWalletEntry, ...],
) -> list[WalletEntryPayload]:
    return [to_wallet_entry_payload(entry) for entry in wallet_entries]


__all__ = [
    "AuthenticatedUserCanonicalPayload",
    "AuthenticatedUserBootstrapPayload",
    "AuthenticatedUserBootstrapWalletPayload",
    "AuthenticatedUserFinancialProfilePayload",
    "AuthenticatedUserIdentityPayload",
    "AuthenticatedUserInvestorProfilePayload",
    "AuthenticatedUserProductContextPayload",
    "AuthenticatedUserProfileDetailsPayload",
    "AuthenticatedUserTransactionsPreviewPayload",
    "UserProfilePayload",
    "WalletEntryPayload",
    "to_authenticated_user_bootstrap_payload",
    "to_authenticated_user_canonical_payload",
    "to_transactions_preview_payload",
    "to_user_profile_payload",
    "to_wallet_entry_payload",
    "to_wallet_payload",
    "to_wallet_preview_payload",
]
