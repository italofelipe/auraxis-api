"""LGPD registry — single source of truth for personal-data coverage.

Every entity that stores user-linked data MUST be registered here. The
accompanying test (``tests/lgpd/test_registry.py``) walks the SQLAlchemy
metadata and fails CI if a model with a user-linking column is not registered.

Rules cover:

- :class:`DeletionStrategy` — how the row is handled on account deletion
- ``export_included`` — whether the entity ships in ``/user/me/export``
- :class:`RetentionReason` + ``retention_days`` — legal/audit retention

This module is intentionally free of business logic; it only declares rules.
Consumer modules (export endpoint, delete-me service, AI minimisation
tracker) read this registry to drive their behaviour.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterator, MutableSequence
from dataclasses import dataclass
from enum import Enum

from app.extensions.database import db

# Column names that indicate a row is linked to a user. ``id`` only counts when
# the model is the ``User`` itself (the base entity). Other patterns observed
# in the codebase: ``user_id`` (standard FK), ``owner_id`` (SharedEntry —
# owner of a shared transaction), ``from_user_id`` / ``to_user_id``
# (Invitation — sender and recipient).
USER_LINK_COLUMNS: frozenset[str] = frozenset(
    {"user_id", "owner_id", "from_user_id", "to_user_id"}
)


class DeletionStrategy(str, Enum):
    """How a row is handled when the user requests account deletion."""

    # Hard delete — row is removed. Use for purely user-owned data with no
    # legal retention obligation.
    DELETE = "delete"
    # Keep row but null PII fields. Use when foreign keys would break
    # referential integrity or when aggregate audit needs the structure.
    ANONYMIZE = "anonymize"
    # Keep row entirely. Use only when a legal obligation overrides LGPD
    # erasure (Brazilian fiscal records, billing receipts, etc).
    RETAIN = "retain"


class RetentionReason(str, Enum):
    """Why a row may be retained beyond active account life."""

    # No retention beyond the active life of the account.
    NONE = "none"
    # Brazilian tax law — fiscal documents must be kept for 5 years minimum.
    FISCAL = "fiscal"
    # Internal compliance audit (typically 1 year).
    AUDIT = "audit"
    # LGPD process evidence — consent records, DSR responses.
    LGPD_PROCESS = "lgpd_process"
    # Security incident response window (typically 90 days).
    SECURITY = "security"


@dataclass(frozen=True)
class EntityRule:
    """Registry entry describing one user-linked entity."""

    # SQLAlchemy model class.
    model: type
    # Column name on this model that links to ``users.id``. For the ``User``
    # model itself this is ``"id"``.
    user_id_field: str
    # Database table name (mirrors ``__tablename__``).
    table_name: str
    # How rows are handled on account deletion.
    deletion_strategy: DeletionStrategy
    # Whether the entity is included in ``GET /user/me/export``.
    export_included: bool
    # Why the row may be retained beyond active life.
    retention_reason: RetentionReason
    # Retention window in days. ``None`` means no fixed retention.
    retention_days: int | None
    # One-line description of what this entity stores about the user.
    description: str


def _build_registry() -> list[EntityRule]:
    """Build the registry list.

    Models are imported lazily inside this function to avoid circular imports
    when the LGPD module is loaded during application startup.
    """
    from app.models.account import Account
    from app.models.ai_insight import AIInsight
    from app.models.ai_insight_feedback import AIInsightFeedback
    from app.models.ai_insight_run import AIInsightRun
    from app.models.alert import Alert, AlertPreference
    from app.models.audit_event import AuditEvent
    from app.models.budget import Budget
    from app.models.consent import Consent
    from app.models.credit_card import CreditCard
    from app.models.entitlement import Entitlement
    from app.models.fiscal import (
        FiscalAdjustment,
        FiscalDocument,
        FiscalImport,
        ReceivableEntry,
    )
    from app.models.goal import Goal
    from app.models.goal_contribution import GoalContribution
    from app.models.investment_operation import InvestmentOperation
    from app.models.llm_audit_log import LLMAuditLog
    from app.models.push_subscription import PushSubscription
    from app.models.refresh_token import RefreshToken
    from app.models.shared_entry import Invitation, SharedEntry
    from app.models.sharing_audit import SharingAuditEvent
    from app.models.simulation import Simulation
    from app.models.simulation_quota_usage import SimulationQuotaUsage
    from app.models.subscription import Subscription
    from app.models.tag import Tag
    from app.models.transaction import Transaction
    from app.models.user import User
    from app.models.user_ticker import UserTicker
    from app.models.wallet import Wallet

    return [
        # === User profile (base entity) =====================================
        EntityRule(
            model=User,
            user_id_field="id",
            table_name="users",
            deletion_strategy=DeletionStrategy.ANONYMIZE,
            export_included=True,
            retention_reason=RetentionReason.LGPD_PROCESS,
            retention_days=None,
            description=("User profile, auth credentials and demographic survey"),
        ),
        # === Financial domain (delete on erasure — no legal retention) ======
        EntityRule(
            model=Account,
            user_id_field="user_id",
            table_name="accounts",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="User bank, cash or wallet accounts",
        ),
        EntityRule(
            model=Transaction,
            user_id_field="user_id",
            table_name="transactions",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Income and expense transactions",
        ),
        EntityRule(
            model=Budget,
            user_id_field="user_id",
            table_name="budgets",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Monthly category budget envelopes",
        ),
        EntityRule(
            model=CreditCard,
            user_id_field="user_id",
            table_name="credit_cards",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Credit card metadata (last digits, brand, limits)",
        ),
        EntityRule(
            model=Goal,
            user_id_field="user_id",
            table_name="goals",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Financial goals",
        ),
        EntityRule(
            model=GoalContribution,
            user_id_field="user_id",
            table_name="goal_contributions",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Per-goal contribution entries",
        ),
        EntityRule(
            model=Wallet,
            user_id_field="user_id",
            table_name="wallets",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Investment wallet ledger",
        ),
        EntityRule(
            model=InvestmentOperation,
            user_id_field="user_id",
            table_name="investment_operations",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Investment trades (buy/sell operations)",
        ),
        EntityRule(
            model=UserTicker,
            user_id_field="user_id",
            table_name="user_tickers",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Watched investment tickers",
        ),
        EntityRule(
            model=Tag,
            user_id_field="user_id",
            table_name="tags",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="User-defined transaction tags",
        ),
        EntityRule(
            model=Simulation,
            user_id_field="user_id",
            table_name="simulations",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Saved financial simulations",
        ),
        EntityRule(
            model=SimulationQuotaUsage,
            user_id_field="user_id",
            table_name="simulation_quota_usage",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=False,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Monthly freemium simulation quota counter (#1409)",
        ),
        EntityRule(
            model=Alert,
            user_id_field="user_id",
            table_name="alerts",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=False,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="User-targeted alert dispatch records",
        ),
        EntityRule(
            model=AlertPreference,
            user_id_field="user_id",
            table_name="alert_preferences",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Per-category alert opt-in configuration",
        ),
        # === Fiscal (RETAIN — Brazilian tax law: 5 years) ===================
        EntityRule(
            model=FiscalImport,
            user_id_field="user_id",
            table_name="fiscal_imports",
            deletion_strategy=DeletionStrategy.RETAIN,
            export_included=True,
            retention_reason=RetentionReason.FISCAL,
            retention_days=1825,
            description="CSV fiscal import batch operations",
        ),
        EntityRule(
            model=FiscalDocument,
            user_id_field="user_id",
            table_name="fiscal_documents",
            deletion_strategy=DeletionStrategy.RETAIN,
            export_included=True,
            retention_reason=RetentionReason.FISCAL,
            retention_days=1825,
            description=("Fiscal documents (NF, receipts) — Brazilian tax retention"),
        ),
        EntityRule(
            model=ReceivableEntry,
            user_id_field="user_id",
            table_name="receivable_entries",
            deletion_strategy=DeletionStrategy.RETAIN,
            export_included=True,
            retention_reason=RetentionReason.FISCAL,
            retention_days=1825,
            description="Receivable amounts linked to fiscal documents",
        ),
        EntityRule(
            model=FiscalAdjustment,
            user_id_field="user_id",
            table_name="fiscal_adjustments",
            deletion_strategy=DeletionStrategy.RETAIN,
            export_included=True,
            retention_reason=RetentionReason.FISCAL,
            retention_days=1825,
            description="Manual fiscal adjustments (audit trail)",
        ),
        # === AI / LLM (issue #1258 minimisation scope) ======================
        EntityRule(
            model=AIInsight,
            user_id_field="user_id",
            table_name="ai_insights",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="AI-generated financial insights",
        ),
        EntityRule(
            model=AIInsightFeedback,
            user_id_field="user_id",
            table_name="ai_insight_feedback",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="User ratings/comments on AI-generated insights",
        ),
        EntityRule(
            model=AIInsightRun,
            user_id_field="user_id",
            table_name="ai_insight_runs",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.AUDIT,
            retention_days=30,
            description=("Sanitized AI insight run snapshots and evidence manifests"),
        ),
        EntityRule(
            model=LLMAuditLog,
            user_id_field="user_id",
            table_name="llm_audit_logs",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=False,
            retention_reason=RetentionReason.SECURITY,
            retention_days=90,
            description=(
                "LLM call audit (tokens, cost, prompt hash) — security window"
            ),
        ),
        # === Authentication / Session =======================================
        EntityRule(
            model=RefreshToken,
            user_id_field="user_id",
            table_name="refresh_tokens",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=False,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Refresh tokens (revoked on account deletion)",
        ),
        EntityRule(
            model=PushSubscription,
            user_id_field="user_id",
            table_name="push_subscriptions",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=False,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Web Push subscription endpoints",
        ),
        # === Subscription / Billing =========================================
        EntityRule(
            model=Subscription,
            user_id_field="user_id",
            table_name="subscriptions",
            deletion_strategy=DeletionStrategy.ANONYMIZE,
            export_included=True,
            retention_reason=RetentionReason.FISCAL,
            retention_days=1825,
            description="Billing subscription state (fiscal retention)",
        ),
        EntityRule(
            model=Entitlement,
            user_id_field="user_id",
            table_name="entitlements",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=False,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Feature entitlements derived from subscription",
        ),
        # === Audit (anonymise but retain for incident response) =============
        EntityRule(
            model=AuditEvent,
            user_id_field="user_id",
            table_name="audit_events",
            deletion_strategy=DeletionStrategy.ANONYMIZE,
            export_included=False,
            retention_reason=RetentionReason.AUDIT,
            retention_days=365,
            description="Generic HTTP and entity audit trail",
        ),
        EntityRule(
            model=SharingAuditEvent,
            user_id_field="user_id",
            table_name="sharing_audit_events",
            deletion_strategy=DeletionStrategy.ANONYMIZE,
            export_included=False,
            retention_reason=RetentionReason.AUDIT,
            retention_days=365,
            description="Sharing and invitation domain audit log",
        ),
        # === Sharing (delete on erasure of the participant) =================
        EntityRule(
            model=SharedEntry,
            user_id_field="owner_id",
            table_name="shared_entries",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description="Transactions shared with another user (owner side)",
        ),
        EntityRule(
            model=Invitation,
            user_id_field="from_user_id",
            table_name="invitations",
            deletion_strategy=DeletionStrategy.DELETE,
            export_included=True,
            retention_reason=RetentionReason.NONE,
            retention_days=None,
            description=(
                "Sharing invitations (from_user_id sender, to_user_id recipient)"
            ),
        ),
        # === LGPD process evidence (#1259) ==================================
        # Versioned consent grants/revocations are themselves LGPD-process
        # records. They are exported with the user data and anonymised
        # (not hard-deleted) on account erasure so the historical audit of
        # which versions were ever accepted survives.
        EntityRule(
            model=Consent,
            user_id_field="user_id",
            table_name="consents",
            deletion_strategy=DeletionStrategy.ANONYMIZE,
            export_included=True,
            retention_reason=RetentionReason.LGPD_PROCESS,
            retention_days=None,
            description="Versioned consent grants/revocations (LGPD evidence)",
        ),
    ]


REGISTRY: list[EntityRule] = _build_registry()


def get_registered_models() -> set[type]:
    """Return the set of model classes covered by the registry."""
    return {entry.model for entry in REGISTRY}


def _model_user_link_columns(model: type) -> set[str]:
    """Return the user-linking columns present on the given model.

    The ``User`` model is special-cased: its primary-key ``id`` is the
    user-link itself.
    """
    try:
        columns = {c.name for c in model.__table__.columns}  # type: ignore[attr-defined]
    except AttributeError:
        return set()
    matches = columns & USER_LINK_COLUMNS
    if model.__name__ == "User" and "id" in columns:
        matches = matches | {"id"}
    return matches


def _is_concrete_user_linked_model(obj: object) -> bool:
    """Return True if ``obj`` is a concrete SQLAlchemy model with a user link."""
    if not isinstance(obj, type):
        return False
    if obj is db.Model or not issubclass(obj, db.Model):
        return False
    # Declarative bases / mixins may not have __table__ resolved yet.
    if not hasattr(obj, "__table__"):
        return False
    return bool(_model_user_link_columns(obj))


def _iter_models_in_package(package_path: MutableSequence[str]) -> Iterator[type]:
    """Yield concrete user-linked model classes discovered under ``package_path``."""
    for _, modname, _ in pkgutil.iter_modules(package_path):
        if modname.startswith("_"):
            continue
        module = importlib.import_module(f"app.models.{modname}")
        for name in dir(module):
            obj = getattr(module, name)
            if _is_concrete_user_linked_model(obj):
                yield obj


def find_unregistered_models() -> list[str]:
    """Walk ``app.models`` and return user-linked models not in the registry.

    Returns a sorted list of ``"module.ClassName"`` strings for any SQLAlchemy
    model that exposes a user-linking column (``user_id``, ``owner_id``,
    ``from_user_id``, ``to_user_id`` — or is the ``User`` model itself) and
    is not covered by :data:`REGISTRY`.

    This is the CI gate that prevents silent additions of unregistered user
    data: it is exercised by ``tests/lgpd/test_registry.py``.
    """
    import app.models as models_package

    registered = get_registered_models()
    unregistered = {
        f"{obj.__module__}.{obj.__name__}"
        for obj in _iter_models_in_package(models_package.__path__)
        if obj not in registered
    }
    return sorted(unregistered)
