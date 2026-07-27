"""Tests for analysis_ready_notification_service and the email_reminders
entitlement gate added to transaction_reminder_service (#1207)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from app.application.services.transaction_reminder_service import (
    dispatch_due_transaction_reminders,
)
from app.config.plan_features import PLAN_FEATURES, PREMIUM_FEATURES
from app.extensions.database import db
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import User
from app.services.analysis_ready_notification_service import (
    dispatch_analysis_ready_notification,
)
from app.services.email_provider import get_email_outbox
from app.services.entitlement_service import activate_premium, deactivate_premium

# ---------------------------------------------------------------------------
# plan_features catalog
# ---------------------------------------------------------------------------


def test_email_reminders_in_premium_plan() -> None:
    assert "email_reminders" in PLAN_FEATURES["premium"]


def test_email_reminders_in_trial_plan() -> None:
    assert "email_reminders" in PLAN_FEATURES["trial"]


def test_email_reminders_not_in_free_plan() -> None:
    assert "email_reminders" not in PLAN_FEATURES["free"]


def test_email_reminders_is_a_premium_feature() -> None:
    assert "email_reminders" in PREMIUM_FEATURES


# ---------------------------------------------------------------------------
# analysis_ready_notification_service
# ---------------------------------------------------------------------------


def test_dispatch_analysis_ready_skips_free_user(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Free User",
            email=f"free-{uuid.uuid4()}@test.com",
            password="hash",
        )
        db.session.add(user)
        db.session.commit()
        deactivate_premium(user.id)

        result = dispatch_analysis_ready_notification(user_id=user.id)

        assert result.email_sent is False
        assert result.push_sent is False
        assert result.skipped_reason == "no_entitlement"


def test_dispatch_analysis_ready_sends_email_to_premium_user(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Premium User",
            email=f"premium-{uuid.uuid4()}@test.com",
            password="hash",
        )
        db.session.add(user)
        db.session.commit()
        activate_premium(user.id, expires_at=None)

        outbox = get_email_outbox()
        before = len(outbox)

        result = dispatch_analysis_ready_notification(
            user_id=user.id,
            summary_preview="Seus gastos subiram 10% este mês.",
        )

        assert result.email_sent is True
        assert result.push_sent is False
        assert result.skipped_reason is None
        assert len(outbox) == before + 1
        sent = outbox[-1]
        subject = sent["subject"].lower()
        assert "análise" in subject or "pronta" in subject
        assert "Premium User".split()[0] in sent["subject"]


def test_dispatch_analysis_ready_embeds_the_insight_content(app) -> None:
    """#1617 — the email carries the insight items, not only the summary."""
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Content User",
            email=f"content-{uuid.uuid4()}@test.com",
            password="hash",
        )
        db.session.add(user)
        db.session.commit()
        activate_premium(user.id, expires_at=None)

        outbox = get_email_outbox()
        result = dispatch_analysis_ready_notification(
            user_id=user.id,
            summary_preview="Seus gastos subiram 10% este mês.",
            insight_payload={
                "items": [
                    {
                        "type": "gasto_elevado",
                        "title": "Delivery subiu 34%",
                        "message": "Você gastou R$ 620 com delivery no mês.",
                        "evidence": ["spending.by_category.delivery"],
                    },
                    {
                        "type": "oportunidade_economia",
                        "title": "Teto de delivery",
                        "message": "Definir um teto de R$ 480 devolve R$ 140 por mês.",
                        "evidence": ["spending.by_category.delivery"],
                    },
                ]
            },
        )

        assert result.email_sent is True
        sent = outbox[-1]
        assert "Delivery subiu 34%" in sent["html"]
        assert "Você gastou R$ 620 com delivery no mês." in sent["html"]
        assert "Delivery subiu 34%" in sent["text"]
        # the actionable item is promoted to the highlighted suggestion
        assert "Definir um teto de R$ 480 devolve R$ 140 por mês." in sent["html"]
        assert "Sugestão" in sent["text"]


def test_dispatch_analysis_ready_tolerates_malformed_insight_payload(app) -> None:
    """A broken payload must not stop the email — just drop the extra section."""
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Broken User",
            email=f"broken-{uuid.uuid4()}@test.com",
            password="hash",
        )
        db.session.add(user)
        db.session.commit()
        activate_premium(user.id, expires_at=None)

        outbox = get_email_outbox()
        before = len(outbox)
        result = dispatch_analysis_ready_notification(
            user_id=user.id,
            summary_preview="Resumo.",
            insight_payload={"items": "not-a-list"},
        )

        assert result.email_sent is True
        assert len(outbox) == before + 1
        assert "Sugestão" not in outbox[-1]["html"]


def test_dispatch_analysis_ready_skips_nonexistent_user(app) -> None:
    # A non-existent user has no entitlement rows, so the gate fires first.
    with app.app_context():
        fake_id = uuid.uuid4()
        result = dispatch_analysis_ready_notification(user_id=fake_id)

        assert result.email_sent is False
        assert result.skipped_reason in ("no_entitlement", "user_not_found")


def test_dispatch_analysis_ready_sends_expo_push_to_premium_user(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Push User",
            email=f"push-{uuid.uuid4()}@test.com",
            password="hash",
        )
        db.session.add(user)
        db.session.commit()
        activate_premium(user.id, expires_at=None)

        from app.models.push_subscription import PushSubscription, PushTransport

        sub = PushSubscription(
            user_id=user.id,
            transport=PushTransport.expo,
            endpoint=f"ExponentPushToken[test-{uuid.uuid4()}]",
        )
        db.session.add(sub)
        db.session.commit()

        with patch(
            "app.services.analysis_ready_notification_service.http_client.post"
        ) as mock_post:
            mock_post.return_value.ok = True
            result = dispatch_analysis_ready_notification(
                user_id=user.id,
                summary_preview="Gastos acima do esperado.",
            )

        assert result.push_sent is True
        mock_post.assert_called_once()
        call_body = mock_post.call_args.kwargs["json"]
        assert "ExponentPushToken" in call_body["to"]
        assert "Análise" in call_body["title"] or "pronta" in call_body["title"]


def test_dispatch_analysis_ready_handles_email_failure(app) -> None:
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Error User",
            email=f"err-{uuid.uuid4()}@test.com",
            password="hash",
        )
        db.session.add(user)
        db.session.commit()
        activate_premium(user.id, expires_at=None)

        with patch(
            "app.services.analysis_ready_notification_service.get_default_email_provider"
        ) as mock_provider:
            mock_provider.return_value.send.side_effect = RuntimeError("SMTP down")
            result = dispatch_analysis_ready_notification(user_id=user.id)

        assert result.email_sent is False


# ---------------------------------------------------------------------------
# transaction_reminder_service — entitlement gate
# ---------------------------------------------------------------------------


def test_reminder_skips_free_user_with_email_reminders_gate(app) -> None:
    """Free users must NOT receive transaction reminders after the gate."""
    today = date(2030, 8, 1)
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Free Reminder",
            email=f"free-reminder-{uuid.uuid4()}@test.com",
            password="hash",
        )
        db.session.add(user)
        db.session.flush()
        deactivate_premium(user.id)

        transaction = Transaction(
            user_id=user.id,
            title="Conta de água",
            amount=Decimal("80.00"),
            type=TransactionType.EXPENSE,
            status=TransactionStatus.PENDING,
            due_date=today + timedelta(days=7),
        )
        db.session.add(transaction)
        db.session.commit()

        outbox = get_email_outbox()
        before = len(outbox)
        result = dispatch_due_transaction_reminders(days_before_due=7, today=today)

        assert len(outbox) == before, "Free user should not receive reminder email"
        assert result.skipped >= 1


def test_reminder_sends_to_premium_user(app) -> None:
    """Premium users MUST receive transaction reminders."""
    today = date(2030, 9, 1)
    with app.app_context():
        user = User(
            id=uuid.uuid4(),
            name="Premium Reminder",
            email=f"prem-reminder-{uuid.uuid4()}@test.com",
            password="hash",
        )
        db.session.add(user)
        db.session.flush()
        activate_premium(user.id, expires_at=None)

        transaction = Transaction(
            user_id=user.id,
            title="Aluguel",
            amount=Decimal("1500.00"),
            type=TransactionType.EXPENSE,
            status=TransactionStatus.PENDING,
            due_date=today + timedelta(days=7),
        )
        db.session.add(transaction)
        db.session.commit()

        outbox = get_email_outbox()
        before = len(outbox)
        result = dispatch_due_transaction_reminders(days_before_due=7, today=today)

        assert result.sent >= 1
        assert len(outbox) >= before + 1
