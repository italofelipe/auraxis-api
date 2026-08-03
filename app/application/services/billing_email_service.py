from __future__ import annotations

from typing import TYPE_CHECKING

from app.controllers.billing_webhook_parsers import (
    ASAAS_CHARGEBACK_EVENTS,
    ASAAS_REFUND_EVENTS,
)
from app.services.email_provider import EmailMessage
from app.services.email_templates.base import (
    render_billing_canceled_email,
    render_billing_grace_expired_email,
    render_billing_payment_confirmed_email,
    render_billing_payment_failed_email,
    render_billing_refund_email,
    render_billing_trial_ending_email,
    render_billing_trial_expired_email,
)

if TYPE_CHECKING:
    from app.models.subscription import Subscription
    from app.models.user import User

_PAYMENT_CONFIRMED_EVENTS = {"PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"}
_PAYMENT_FAILED_EVENTS = {"PAYMENT_OVERDUE", "subscription.past_due"}
_CANCELED_EVENTS = {"subscription.canceled", "SUBSCRIPTION_DELETED"}
# #1598 — refund/chargeback notice; event strings owned by
# billing_webhook_parsers (single source of truth, guarded by a parity test).
_REFUND_EVENTS = ASAAS_REFUND_EVENTS | ASAAS_CHARGEBACK_EVENTS

_TRIAL_ENDING_TAG_TEMPLATE = "billing_trial_ending_{days}d"
_TRIAL_EXPIRED_TAG = "billing_trial_expired"


def _plan_label(subscription: Subscription) -> str:
    if subscription.billing_cycle is None:
        return str(subscription.plan_code)
    return f"{subscription.plan_code} {str(subscription.billing_cycle.value)}"


def dispatch_billing_email(
    *, user: User, subscription: Subscription, event_type: str
) -> None:
    """Route a billing webhook event to its branded transactional email."""
    from app.services.outbound_queue import get_default_outbound_queue

    plan_label = _plan_label(subscription)

    if event_type in _PAYMENT_CONFIRMED_EVENTS:
        html, text = render_billing_payment_confirmed_email(plan_label=plan_label)
        tag = "billing_payment_confirmed"
        subject = "Pagamento confirmado na Auraxis"
    elif event_type in _PAYMENT_FAILED_EVENTS:
        html, text = render_billing_payment_failed_email(plan_label=plan_label)
        tag = "billing_payment_failed"
        subject = "Pagamento pendente na Auraxis"
    elif event_type in _REFUND_EVENTS:
        html, text = render_billing_refund_email(plan_label=plan_label)
        tag = "billing_refund"
        subject = "Estorno processado — Auraxis"
    elif event_type in _CANCELED_EVENTS:
        html, text = render_billing_canceled_email(plan_label=plan_label)
        tag = "billing_subscription_canceled"
        subject = "Assinatura cancelada na Auraxis"
    else:
        return

    get_default_outbound_queue().enqueue_send_email(
        to_email=str(user.email),
        subject=subject,
        html=html,
        text=text,
        tag=tag,
    )


def build_trial_ending_email(
    *, user: User, subscription: Subscription, days_until_trial_end: int
) -> EmailMessage:
    """Build the D-N "trial acabando" dunning email (#1555).

    Content only — scanning, idempotency and delivery live in
    ``trial_ending_reminder_service``.
    """
    days_label = (
        "1 dia" if days_until_trial_end == 1 else f"{days_until_trial_end} dias"
    )
    trial_ends_label = (
        subscription.trial_ends_at.strftime("%d/%m/%Y")
        if subscription.trial_ends_at is not None
        else None
    )
    html, text = render_billing_trial_ending_email(
        days_label=days_label, trial_ends_label=trial_ends_label
    )
    return EmailMessage(
        to_email=str(user.email),
        subject=f"Seu período de teste termina em {days_label} — Auraxis",
        html=html,
        text=text,
        tag=_TRIAL_ENDING_TAG_TEMPLATE.format(days=days_until_trial_end),
    )


def dispatch_trial_expired_email(*, user: User, subscription: Subscription) -> None:
    """Notify the user that the trial ended and the downgrade was applied (#1555).

    Called by ``scripts/process_trial_expirations.py`` after the TRIALING →
    FREE downgrade is committed.
    """
    from app.services.outbound_queue import get_default_outbound_queue

    html, text = render_billing_trial_expired_email(
        plan_label=_plan_label(subscription)
    )
    get_default_outbound_queue().enqueue_send_email(
        to_email=str(user.email),
        subject="Seu período de teste terminou — Auraxis",
        html=html,
        text=text,
        tag=_TRIAL_EXPIRED_TAG,
    )


def dispatch_billing_grace_expired_email(
    *, user: User, subscription: Subscription
) -> None:
    """Notify that the dunning grace window lapsed unpaid and premium ended (#1599).

    Called by ``scripts/process_grace_expirations.py`` after the PAST_DUE →
    EXPIRED downgrade is committed.
    """
    from app.services.outbound_queue import get_default_outbound_queue

    html, text = render_billing_grace_expired_email(
        plan_label=_plan_label(subscription)
    )
    get_default_outbound_queue().enqueue_send_email(
        to_email=str(user.email),
        subject="Assinatura encerrada por falta de pagamento — Auraxis",
        html=html,
        text=text,
        tag="billing_grace_expired",
    )
