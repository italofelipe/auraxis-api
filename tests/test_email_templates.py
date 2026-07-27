"""Tests for Auraxis branded email templates (light identity redesign).

Covers the shared shell (doctype, brand colour, wordmark), every renderer's
(html, text) contract, the deep-link CTAs (transaction + insight) and the
env-driven base URL.
"""

from __future__ import annotations

from app.services.email_templates import (
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

CONFIRM_URL = "https://app.auraxis.com.br/confirm-email?token=abc123"
RESET_URL = "https://app.auraxis.com.br/reset-password?token=xyz456"
_BRAND = "#087fa7"  # brand teal (light identity)


def _is_email(result: tuple[str, str]) -> None:
    html, text = result
    assert html.strip().startswith("<!DOCTYPE html>")
    assert _BRAND in html  # every email carries the brand identity
    assert "Auraxis" in html
    assert "<" not in text  # plain-text fallback


class TestConfirmationEmail:
    def test_contract_and_identity(self) -> None:
        _is_email(render_confirmation_email(confirmation_url=CONFIRM_URL))

    def test_cta_and_url(self) -> None:
        html, text = render_confirmation_email(confirmation_url=CONFIRM_URL)
        assert CONFIRM_URL in html
        assert CONFIRM_URL in text
        assert "Confirmar meu email" in html
        assert "24 horas" in html


class TestPasswordResetEmail:
    def test_contract_and_identity(self) -> None:
        _is_email(render_password_reset_email(reset_url=RESET_URL))

    def test_cta_and_url(self) -> None:
        html, text = render_password_reset_email(reset_url=RESET_URL)
        assert RESET_URL in html
        assert RESET_URL in text
        assert "Criar nova senha" in html
        assert "1 hora" in html


class TestAccountDeletionEmail:
    def test_contract_and_lgpd(self) -> None:
        html, text = render_account_deletion_email()
        _is_email((html, text))
        assert "LGPD" in html


class TestDueSoonEmail:
    def test_contract(self) -> None:
        _is_email(
            render_due_soon_email(
                title="Aluguel", amount_formatted="1500.00", days_before_due=7
            )
        )

    def test_deep_link_cta(self) -> None:
        url = "https://app.auraxis.com.br/transactions?open=tx-42"
        html, text = render_due_soon_email(
            title="Aluguel",
            amount_formatted="1500.00",
            days_before_due=1,
            due_date_label="27/07/2026",
            transaction_url=url,
        )
        assert "Ver transação" in html
        assert url in html  # CTA deep-links to the exact transaction
        assert url in text
        assert "Aluguel" in html and "1500.00" in html
        assert "Vence amanhã" in html

    def test_d7_badge_and_content(self) -> None:
        html, _ = render_due_soon_email(
            title="Cartão", amount_formatted="320.50", days_before_due=7
        )
        assert "Vence em 7 dias" in html
        assert "Cartão" in html and "320.50" in html

    def test_falls_back_to_transactions_list_without_url(self) -> None:
        html, _ = render_due_soon_email(
            title="Aluguel", amount_formatted="1500.00", days_before_due=7
        )
        assert "/transactions" in html


class TestInsightEmails:
    def test_weekly_deep_links_to_insight(self) -> None:
        url = "https://app.auraxis.com.br/insights?open=ins-7"
        html, text = render_analysis_ready_email(
            first_name="Italo",
            summary_preview="Seus gastos com delivery subiram 34%.",
            insight_url=url,
            items=[("Delivery subiu 34%", "Você gastou R$ 620 com delivery.")],
            suggestion="definir um teto mensal de R$ 480.",
        )
        _is_email((html, text))
        assert "Abrir no Auraxis" in html
        assert url in html
        assert "Sugestão" in html

    def test_weekly_embeds_the_full_insight(self) -> None:
        html, text = render_analysis_ready_email(
            first_name="Italo",
            summary_preview="Resumo.",
            items=[
                ("Delivery subiu 34%", "Você gastou R$ 620 com delivery."),
                ("Assinaturas paradas", "R$ 89 em serviços sem uso há 60 dias."),
            ],
        )
        # Both the HTML body and the plain-text fallback carry every item
        for title, message in (
            ("Delivery subiu 34%", "Você gastou R$ 620 com delivery."),
            ("Assinaturas paradas", "R$ 89 em serviços sem uso há 60 dias."),
        ):
            assert title in html and message in html
            assert title in text and message in text

    def test_llm_content_is_escaped_in_html(self) -> None:
        html, text = render_analysis_ready_email(
            first_name="Italo",
            summary_preview="Resumo.",
            items=[("<b>Alerta</b>", "Gasto & receita <script>alert(1)</script>")],
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert "&amp;" in html
        # the plain-text part carries the raw content — no HTML entities there
        assert "&lt;" not in text and "&amp;" not in text

    def test_weekly_without_items_still_renders(self) -> None:
        html, text = render_analysis_ready_email(
            first_name="Italo", summary_preview="Resumo sem itens."
        )
        _is_email((html, text))
        assert "Resumo sem itens." in html
        assert "Sugestão" not in html

    def test_weekly_without_insight_id_falls_back(self) -> None:
        html, _ = render_analysis_ready_email(
            first_name="Italo", summary_preview="Resumo."
        )
        assert "/insights" in html

    def test_monthly_deep_links(self) -> None:
        url = "https://app.auraxis.com.br/insights?open=month-3"
        html, text = render_monthly_analysis_ready_email(
            first_name="Italo",
            summary_preview="Consolidado do mês.",
            insight_url=url,
        )
        _is_email((html, text))
        assert url in html
        assert "Abrir relatório" in html

    def test_monthly_embeds_the_full_insight(self) -> None:
        html, text = render_monthly_analysis_ready_email(
            first_name="Italo",
            summary_preview="Consolidado do mês.",
            insight_url="https://app.auraxis.com.br/insights?open=month-3",
            items=[("Mercado estável", "R$ 1.240 no mês, em linha com a média.")],
            suggestion="manter o teto de R$ 1.300 para o próximo mês.",
        )
        assert "Mercado estável" in html
        assert "R$ 1.240 no mês, em linha com a média." in html
        assert "Mercado estável" in text
        assert "Sugestão" in html and "Sugestão" in text


class TestVerificationReminderEmail:
    def test_d1_and_d7(self) -> None:
        html1, _ = render_email_verification_reminder_email(days_until_deadline=1)
        _is_email((html1, _))
        assert "Último dia" in html1
        html7, _ = render_email_verification_reminder_email(days_until_deadline=7)
        assert "7 dias" in html7


class TestBillingEmails:
    def test_all_billing_renderers_carry_identity_and_plan(self) -> None:
        plan = "premium annual"
        renderers = [
            render_billing_payment_confirmed_email,
            render_billing_payment_failed_email,
            render_billing_refund_email,
            render_billing_canceled_email,
            render_billing_trial_expired_email,
            render_billing_grace_expired_email,
        ]
        for renderer in renderers:
            html, text = renderer(plan_label=plan)
            _is_email((html, text))
            assert plan in html
            assert plan in text

    def test_trial_ending_email(self) -> None:
        html, text = render_billing_trial_ending_email(
            days_label="2 dias", trial_ends_label="27/07/2026"
        )
        _is_email((html, text))
        assert "2 dias" in html
        assert "27/07/2026" in html


class TestWebBaseUrl:
    def test_env_override(self, monkeypatch) -> None:
        monkeypatch.setenv("AURAXIS_WEB_BASE_URL", "https://staging.auraxis.com.br/")
        assert web_base_url() == "https://staging.auraxis.com.br"

    def test_default(self, monkeypatch) -> None:
        monkeypatch.delenv("AURAXIS_WEB_BASE_URL", raising=False)
        monkeypatch.delenv("AURAXIS_APP_URL", raising=False)
        assert web_base_url() == "https://app.auraxis.com.br"
