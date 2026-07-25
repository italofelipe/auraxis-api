"""Unit tests for J-task domain models (GH #618).

Covers:
  Simulation, Subscription, Entitlement, SharedEntry, Invitation,
  FiscalDocument, ReceivableEntry, Alert, AlertPreference
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.extensions.database import db
from app.models.alert import Alert, AlertPreference, AlertStatus
from app.models.entitlement import Entitlement, EntitlementSource
from app.models.fiscal import (
    FiscalDocument,
    FiscalDocumentStatus,
    FiscalDocumentType,
    ReceivableEntry,
    ReconciliationStatus,
)
from app.models.shared_entry import (
    Invitation,
    InvitationStatus,
    SharedEntry,
    SharedEntryStatus,
    SplitType,
)
from app.models.simulation import Simulation
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.transaction import Transaction, TransactionType
from app.models.user import User

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(suffix: str = "") -> User:
    user = User(
        name=f"j-task-test-user{suffix}",
        email=f"j-task-test{suffix}@auraxis.test",
        password="StrongPass@123",
    )
    db.session.add(user)
    db.session.flush()
    return user


def _make_transaction(user: User, title: str = "test txn") -> Transaction:
    txn = Transaction(
        user_id=user.id,
        title=title,
        amount=Decimal("80.00"),
        type=TransactionType.EXPENSE,
        due_date=datetime.utcnow().date(),
    )
    db.session.add(txn)
    db.session.flush()
    return txn


# ===========================================================================
# Simulation
# ===========================================================================


def test_simulation_persists_with_required_fields(app) -> None:
    with app.app_context():
        user = _make_user("-sim1")
        sim = Simulation(
            user_id=user.id,
            tool_id="salary_net",
            rule_version="2025.1",
            inputs={"gross": 5000},
            result={"net": 4100},
        )
        db.session.add(sim)
        db.session.commit()

        stored = Simulation.query.filter_by(id=sim.id).first()
        assert stored is not None
        assert stored.tool_id == "salary_net"
        assert stored.rule_version == "2025.1"
        assert stored.inputs == {"gross": 5000}
        assert stored.result == {"net": 4100}
        assert stored.saved is False
        assert stored.created_at is not None


def test_simulation_repr(app) -> None:
    with app.app_context():
        user = _make_user("-sim2")
        sim = Simulation(
            user_id=user.id,
            tool_id="rescission",
            rule_version="2025.1",
            inputs={},
            result={},
        )
        db.session.add(sim)
        db.session.commit()
        assert "rescission" in repr(sim)


def test_simulation_anonymous_allowed(app) -> None:
    """user_id is nullable — anonymous simulations are valid."""
    with app.app_context():
        sim = Simulation(
            tool_id="salary_net",
            rule_version="2025.1",
            inputs={"gross": 3000},
            result={"net": 2600},
        )
        db.session.add(sim)
        db.session.commit()
        assert sim.user_id is None


# ===========================================================================
# Subscription
# ===========================================================================


def test_subscription_defaults_to_free(app) -> None:
    with app.app_context():
        user = _make_user("-sub1")
        sub = Subscription(
            user_id=user.id,
            plan_code="free",
        )
        db.session.add(sub)
        db.session.commit()

        stored = Subscription.query.filter_by(id=sub.id).first()
        assert stored is not None
        assert stored.status == SubscriptionStatus.FREE
        assert stored.plan_code == "free"
        assert stored.created_at is not None
        assert stored.updated_at is not None


def test_subscription_active_status(app) -> None:
    with app.app_context():
        user = _make_user("-sub2")
        sub = Subscription(
            user_id=user.id,
            plan_code="pro",
            status=SubscriptionStatus.ACTIVE,
            billing_cycle=BillingCycle.MONTHLY,
            provider="asaas",
        )
        db.session.add(sub)
        db.session.commit()

        stored = Subscription.query.filter_by(id=sub.id).first()
        assert stored is not None
        assert stored.status == SubscriptionStatus.ACTIVE
        assert stored.billing_cycle == BillingCycle.MONTHLY
        assert stored.provider == "asaas"


def test_subscription_repr(app) -> None:
    with app.app_context():
        user = _make_user("-sub3")
        sub = Subscription(user_id=user.id, plan_code="pro")
        db.session.add(sub)
        db.session.commit()
        r = repr(sub)
        assert "pro" in r


# ===========================================================================
# Entitlement
# ===========================================================================


def test_entitlement_persists_with_required_fields(app) -> None:
    with app.app_context():
        user = _make_user("-ent1")
        ent = Entitlement(
            user_id=user.id,
            feature_key="export_pdf",
            source=EntitlementSource.SUBSCRIPTION,
        )
        db.session.add(ent)
        db.session.commit()

        stored = Entitlement.query.filter_by(id=ent.id).first()
        assert stored is not None
        assert stored.feature_key == "export_pdf"
        assert stored.source == EntitlementSource.SUBSCRIPTION
        assert stored.expires_at is None
        assert stored.created_at is not None


def test_entitlement_with_expiry(app) -> None:
    with app.app_context():
        user = _make_user("-ent2")
        expires = datetime.utcnow() + timedelta(days=30)
        ent = Entitlement(
            user_id=user.id,
            feature_key="ai_advisor",
            source=EntitlementSource.TRIAL,
            expires_at=expires,
        )
        db.session.add(ent)
        db.session.commit()

        stored = Entitlement.query.filter_by(id=ent.id).first()
        assert stored is not None
        assert stored.source == EntitlementSource.TRIAL
        assert stored.expires_at is not None


def test_entitlement_repr(app) -> None:
    with app.app_context():
        user = _make_user("-ent3")
        ent = Entitlement(
            user_id=user.id,
            feature_key="reports",
            source=EntitlementSource.MANUAL,
        )
        db.session.add(ent)
        db.session.commit()
        r = repr(ent)
        assert "reports" in r
        assert "manual" in r.lower()


# ===========================================================================
# SharedEntry
# ===========================================================================


def test_shared_entry_persists_with_defaults(app) -> None:
    with app.app_context():
        owner = _make_user("-se1")
        txn = _make_transaction(owner, "lunch split")
        entry = SharedEntry(
            owner_id=owner.id,
            transaction_id=txn.id,
            split_type=SplitType.EQUAL,
        )
        db.session.add(entry)
        db.session.commit()

        stored = SharedEntry.query.filter_by(id=entry.id).first()
        assert stored is not None
        assert stored.status == SharedEntryStatus.PENDING
        assert stored.split_type == SplitType.EQUAL
        assert stored.created_at is not None


def test_shared_entry_repr(app) -> None:
    with app.app_context():
        owner = _make_user("-se2")
        txn = _make_transaction(owner, "dinner")
        entry = SharedEntry(
            owner_id=owner.id,
            transaction_id=txn.id,
            split_type=SplitType.PERCENTAGE,
        )
        db.session.add(entry)
        db.session.commit()
        assert "SharedEntry" in repr(entry)


# ===========================================================================
# Invitation
# ===========================================================================


def test_invitation_defaults_to_pending(app) -> None:
    with app.app_context():
        owner = _make_user("-inv1")
        txn = _make_transaction(owner, "taxi")
        entry = SharedEntry(
            owner_id=owner.id,
            transaction_id=txn.id,
            split_type=SplitType.CUSTOM,
        )
        db.session.add(entry)
        db.session.flush()

        inv = Invitation(
            shared_entry_id=entry.id,
            from_user_id=owner.id,
            to_user_email="friend@auraxis.test",
        )
        db.session.add(inv)
        db.session.commit()

        stored = Invitation.query.filter_by(id=inv.id).first()
        assert stored is not None
        assert stored.status == InvitationStatus.PENDING
        assert stored.to_user_email == "friend@auraxis.test"


def test_invitation_repr(app) -> None:
    with app.app_context():
        owner = _make_user("-inv2")
        txn = _make_transaction(owner, "coffee")
        entry = SharedEntry(
            owner_id=owner.id,
            transaction_id=txn.id,
            split_type=SplitType.EQUAL,
        )
        db.session.add(entry)
        db.session.flush()

        inv = Invitation(
            shared_entry_id=entry.id,
            from_user_id=owner.id,
            to_user_email="test2@auraxis.test",
        )
        db.session.add(inv)
        db.session.commit()
        assert "test2@auraxis.test" in repr(inv)


# ===========================================================================
# FiscalDocument
# ===========================================================================


def test_fiscal_document_persists_with_required_fields(app) -> None:
    with app.app_context():
        user = _make_user("-fd1")
        doc = FiscalDocument(
            user_id=user.id,
            external_id="NF-001",
            type=FiscalDocumentType.SERVICE_INVOICE,
            issued_at=datetime.utcnow().date(),
            counterparty="ACME Ltda",
            gross_amount=Decimal("1500.00"),
        )
        db.session.add(doc)
        db.session.commit()

        stored = FiscalDocument.query.filter_by(id=doc.id).first()
        assert stored is not None
        assert stored.external_id == "NF-001"
        assert stored.status == FiscalDocumentStatus.ISSUED
        assert stored.gross_amount == Decimal("1500.00")


def test_fiscal_document_repr(app) -> None:
    with app.app_context():
        user = _make_user("-fd2")
        doc = FiscalDocument(
            user_id=user.id,
            external_id="NF-002",
            type=FiscalDocumentType.RECEIPT,
            issued_at=datetime.utcnow().date(),
            counterparty="Shop XYZ",
            gross_amount=Decimal("200.00"),
        )
        db.session.add(doc)
        db.session.commit()
        assert "NF-002" in repr(doc)


# ===========================================================================
# ReceivableEntry
# ===========================================================================


def test_receivable_entry_defaults_to_pending(app) -> None:
    with app.app_context():
        user = _make_user("-re1")
        doc = FiscalDocument(
            user_id=user.id,
            external_id="NF-REC-001",
            type=FiscalDocumentType.SERVICE_INVOICE,
            issued_at=datetime.utcnow().date(),
            counterparty="Client Corp",
            gross_amount=Decimal("5000.00"),
        )
        db.session.add(doc)
        db.session.flush()

        entry = ReceivableEntry(
            fiscal_document_id=doc.id,
            user_id=user.id,
            expected_net_amount=Decimal("4500.00"),
        )
        db.session.add(entry)
        db.session.commit()

        stored = ReceivableEntry.query.filter_by(id=entry.id).first()
        assert stored is not None
        assert stored.reconciliation_status == ReconciliationStatus.PENDING
        assert stored.received_at is None


def test_receivable_entry_repr(app) -> None:
    with app.app_context():
        user = _make_user("-re2")
        doc = FiscalDocument(
            user_id=user.id,
            external_id="NF-REC-002",
            type=FiscalDocumentType.SERVICE_INVOICE,
            issued_at=datetime.utcnow().date(),
            counterparty="Client B",
            gross_amount=Decimal("2000.00"),
        )
        db.session.add(doc)
        db.session.flush()

        entry = ReceivableEntry(
            fiscal_document_id=doc.id,
            user_id=user.id,
        )
        db.session.add(entry)
        db.session.commit()
        assert "ReceivableEntry" in repr(entry)


# ===========================================================================
# Alert
# ===========================================================================


def test_alert_persists_with_required_fields(app) -> None:
    with app.app_context():
        user = _make_user("-al1")
        alert = Alert(
            user_id=user.id,
            category="due_soon",
            triggered_at=datetime.utcnow(),
        )
        db.session.add(alert)
        db.session.commit()

        stored = Alert.query.filter_by(id=alert.id).first()
        assert stored is not None
        assert stored.category == "due_soon"
        assert stored.status == AlertStatus.PENDING
        assert stored.sent_at is None


def test_alert_status_persists_lowercase_enum_value(app) -> None:
    """Regression for #989: the ``alertstatus`` Postgres enum only declares
    lowercase labels, so the ORM must persist ``AlertStatus.value`` ("sent"),
    not the member name ("SENT"). Without ``values_callable`` the INSERT sent
    "SENT" and Postgres raised InvalidTextRepresentation — which broke every
    reminder/dunning dispatch on days with real work. Asserted at the raw
    column level because SQLite would otherwise round-trip either casing.
    """
    with app.app_context():
        user = _make_user("-al-enum")
        alert = Alert(
            user_id=user.id,
            category="due_soon",
            triggered_at=datetime.utcnow(),
            status=AlertStatus.SENT,
        )
        db.session.add(alert)
        db.session.commit()

        raw_status = db.session.execute(text("SELECT status FROM alerts")).scalar()
        assert raw_status == "sent"

        stored = Alert.query.filter_by(id=alert.id).first()
        assert stored is not None
        assert stored.status == AlertStatus.SENT


def test_alert_repr(app) -> None:
    with app.app_context():
        user = _make_user("-al2")
        alert = Alert(
            user_id=user.id,
            category="overdue",
            triggered_at=datetime.utcnow(),
        )
        db.session.add(alert)
        db.session.commit()
        r = repr(alert)
        assert "overdue" in r
        assert "pending" in r.lower()


# ===========================================================================
# AlertPreference
# ===========================================================================


def test_alert_preference_defaults_enabled(app) -> None:
    with app.app_context():
        user = _make_user("-ap1")
        pref = AlertPreference(
            user_id=user.id,
            category="due_soon",
        )
        db.session.add(pref)
        db.session.commit()

        stored = AlertPreference.query.filter_by(id=pref.id).first()
        assert stored is not None
        assert stored.enabled is True
        assert stored.global_opt_out is False
        assert stored.updated_at is not None


def test_alert_preference_unique_user_category(app) -> None:
    """Two preferences for the same user+category should violate unique constraint."""
    with app.app_context():
        user = _make_user("-ap2")
        pref1 = AlertPreference(user_id=user.id, category="monthly_summary")
        pref2 = AlertPreference(user_id=user.id, category="monthly_summary")
        db.session.add(pref1)
        db.session.flush()
        db.session.add(pref2)
        with pytest.raises(IntegrityError):
            db.session.flush()


def test_alert_preference_repr(app) -> None:
    with app.app_context():
        user = _make_user("-ap3")
        pref = AlertPreference(user_id=user.id, category="onboarding_pending")
        db.session.add(pref)
        db.session.commit()
        r = repr(pref)
        assert "onboarding_pending" in r
