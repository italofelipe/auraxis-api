from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.email_provider import EmailMessage

if TYPE_CHECKING:
    from app.models.subscription import Subscription
    from app.models.user import User

_PAYMENT_CONFIRMED_EVENTS = {"PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"}
_PAYMENT_FAILED_EVENTS = {"PAYMENT_OVERDUE", "subscription.past_due"}
_CANCELED_EVENTS = {"subscription.canceled", "SUBSCRIPTION_DELETED"}

_TRIAL_ENDING_TAG_TEMPLATE = "billing_trial_ending_{days}d"
_TRIAL_EXPIRED_TAG = "billing_trial_expired"


def _plan_label(subscription: Subscription) -> str:
    if subscription.billing_cycle is None:
        return str(subscription.plan_code)
    return f"{subscription.plan_code} {str(subscription.billing_cycle.value)}"


def dispatch_billing_email(
    *, user: User, subscription: Subscription, event_type: str
) -> None:
    from app.services.outbound_queue import get_default_outbound_queue

    plan_label = _plan_label(subscription)
    to_email = str(user.email)

    if event_type in _PAYMENT_CONFIRMED_EVENTS:
        get_default_outbound_queue().enqueue_send_email(
            to_email=to_email,
            subject="Pagamento confirmado na Auraxis",
            html=(
                "<p>Seu pagamento foi confirmado com sucesso.</p>"
                f"<p>Plano ativo: <strong>{plan_label}</strong></p>"
            ),
            text=(
                f"Seu pagamento foi confirmado com sucesso. Plano ativo: {plan_label}."
            ),
            tag="billing_payment_confirmed",
        )
        return

    if event_type in _PAYMENT_FAILED_EVENTS:
        get_default_outbound_queue().enqueue_send_email(
            to_email=to_email,
            subject="Pagamento pendente na Auraxis",
            html=(
                "<p>Identificamos uma pendencia no pagamento da sua assinatura.</p>"
                f"<p>Plano impactado: <strong>{plan_label}</strong></p>"
            ),
            text=(
                "Identificamos uma pendencia no pagamento da sua assinatura. "
                f"Plano impactado: {plan_label}."
            ),
            tag="billing_payment_failed",
        )
        return

    if event_type in _CANCELED_EVENTS:
        get_default_outbound_queue().enqueue_send_email(
            to_email=to_email,
            subject="Assinatura cancelada na Auraxis",
            html=(
                "<p>Sua assinatura foi cancelada.</p>"
                f"<p>Plano anterior: <strong>{plan_label}</strong></p>"
            ),
            text=(f"Sua assinatura foi cancelada. Plano anterior: {plan_label}."),
            tag="billing_subscription_canceled",
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
    ends_sentence = f" Ele termina em {trial_ends_label}." if trial_ends_label else ""
    return EmailMessage(
        to_email=str(user.email),
        subject=f"Seu período de teste termina em {days_label} — Auraxis",
        html=(
            f"<p>Seu período de teste da Auraxis termina em "
            f"<strong>{days_label}</strong>.{ends_sentence}</p>"
            "<p>Assine um plano para continuar com acesso aos recursos "
            "premium — exportação em PDF, simulações avançadas e mais.</p>"
        ),
        text=(
            f"Seu período de teste da Auraxis termina em {days_label}."
            f"{ends_sentence} "
            "Assine um plano para continuar com acesso aos recursos premium."
        ),
        tag=_TRIAL_ENDING_TAG_TEMPLATE.format(days=days_until_trial_end),
    )


def dispatch_trial_expired_email(*, user: User, subscription: Subscription) -> None:
    """Notify the user that the trial ended and the downgrade was applied (#1555).

    Called by ``scripts/process_trial_expirations.py`` after the TRIALING →
    FREE downgrade is committed.
    """
    from app.services.outbound_queue import get_default_outbound_queue

    plan_label = _plan_label(subscription)
    get_default_outbound_queue().enqueue_send_email(
        to_email=str(user.email),
        subject="Seu período de teste terminou — Auraxis",
        html=(
            "<p>Seu período de teste da Auraxis terminou e sua conta voltou "
            f"para o plano <strong>{plan_label}</strong>.</p>"
            "<p>Você pode assinar a qualquer momento para recuperar o acesso "
            "aos recursos premium.</p>"
        ),
        text=(
            "Seu período de teste da Auraxis terminou e sua conta voltou para "
            f"o plano {plan_label}. Assine a qualquer momento para recuperar "
            "o acesso aos recursos premium."
        ),
        tag=_TRIAL_EXPIRED_TAG,
    )
