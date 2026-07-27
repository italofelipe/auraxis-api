"""Auraxis branded email templates."""

from .base import (
    render_account_deletion_email,
    render_analysis_ready_email,
    render_billing_canceled_email,
    render_billing_grace_expired_email,
    render_billing_payment_confirmed_email,
    render_billing_payment_failed_email,
    render_billing_refund_email,
    render_billing_trial_ending_email,
    render_billing_trial_expired_email,
    render_confirmation_email,
    render_due_soon_email,
    render_email_verification_reminder_email,
    render_monthly_analysis_ready_email,
    render_password_reset_email,
    web_base_url,
)

__all__ = [
    "render_account_deletion_email",
    "render_analysis_ready_email",
    "render_billing_canceled_email",
    "render_billing_grace_expired_email",
    "render_billing_payment_confirmed_email",
    "render_billing_payment_failed_email",
    "render_billing_refund_email",
    "render_billing_trial_ending_email",
    "render_billing_trial_expired_email",
    "render_confirmation_email",
    "render_due_soon_email",
    "render_email_verification_reminder_email",
    "render_monthly_analysis_ready_email",
    "render_password_reset_email",
    "web_base_url",
]
