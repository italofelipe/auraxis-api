"""Auraxis transactional email template system.

A single, component-based **light** layout that matches the auraxis-web brand
(teal ``#087fa7`` → green ``#087f5b`` gradient, navy ink, purple accent),
replacing the previous dark "Market Pulse" shell. Every transactional email —
auth, reminders, billing and AI insights — renders through ``_base_layout`` so
the identity, spacing and CTA style stay consistent.

Usage::

    from app.services.email_templates.base import render_confirmation_email

    html, text = render_confirmation_email(confirmation_url="https://...")
"""

from __future__ import annotations

import os
from html import escape

# ---------------------------------------------------------------------------
# Brand tokens (light — mirrored from auraxis-web app/assets/css/main.css)
# ---------------------------------------------------------------------------

_COLOR_BG = "#eef3f7"  # page canvas
_COLOR_CARD = "#ffffff"  # email card
_COLOR_BRAND = "#087fa7"  # brand teal (--color-brand-500)
_COLOR_BRAND_DARK = "#066985"  # --color-brand-600
_COLOR_GREEN = "#087f5b"  # --color-positive
_COLOR_ON_BRAND = "#ffffff"
_COLOR_INK = "#0a1628"  # --color-text-primary
_COLOR_INK_SOFT = "#263a56"  # --color-text-secondary
_COLOR_MUTED = "#5d6f89"  # --color-text-muted
_COLOR_SUBTLE = "#7a8ba3"  # --color-text-subtle
_COLOR_BORDER = "#e6edf3"
_COLOR_SURFACE = "#f4f8fb"  # --color-neutral-100
_COLOR_POSITIVE = "#087f5b"
_COLOR_NEGATIVE = "#c2414d"  # --color-negative
_COLOR_WARNING_BG = "rgba(183, 121, 31, 0.14)"
_COLOR_WARNING_TEXT = "#8e5e13"  # --color-warning-dark
_COLOR_ACCENT_BG = "rgba(111, 98, 226, 0.14)"
_COLOR_ACCENT_TEXT = "#5a4fd0"

_FONT = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
    "'Helvetica Neue', Arial, sans-serif"
)

_DEFAULT_WEB_URL = "https://app.auraxis.com.br"


def web_base_url() -> str:
    """Frontend base URL for deep links, env-driven (staging vs prod).

    Reads ``AURAXIS_WEB_BASE_URL`` then ``AURAXIS_APP_URL``; falls back to the
    canonical prod URL. Trailing slash stripped so callers can append paths.
    """
    for var in ("AURAXIS_WEB_BASE_URL", "AURAXIS_APP_URL"):
        value = os.getenv(var, "").strip()
        if value:
            return value.rstrip("/")
    return _DEFAULT_WEB_URL


# ---------------------------------------------------------------------------
# Reusable components (inline-styled for email-client compatibility)
# ---------------------------------------------------------------------------


def _button(url: str, label: str) -> str:
    """A branded CTA button with an Outlook (MSO) fallback."""
    return f"""
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin: 24px 0 8px;">
        <tr>
          <td align="left" style="border-radius: 10px; background-color: {_COLOR_BRAND};">
            <!--[if mso]>
            <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word"
              href="{url}" style="height:46px;v-text-anchor:middle;width:240px;" arcsize="20%"
              strokecolor="{_COLOR_BRAND_DARK}" fillcolor="{_COLOR_BRAND}">
              <w:anchorlock/>
              <center style="color:{_COLOR_ON_BRAND};font-family:{_FONT};font-size:15px;font-weight:600;">{label}</center>
            </v:roundrect>
            <![endif]-->
            <!--[if !mso]><!-->
            <a href="{url}" style="display: inline-block; padding: 13px 28px; font-family: {_FONT};
               font-size: 15px; font-weight: 600; color: {_COLOR_ON_BRAND}; text-decoration: none;
               border-radius: 10px;">{label}</a>
            <!--<![endif]-->
          </td>
        </tr>
      </table>
    """


_BADGE_VARIANTS = {
    "warning": (_COLOR_WARNING_BG, _COLOR_WARNING_TEXT),
    "accent": (_COLOR_ACCENT_BG, _COLOR_ACCENT_TEXT),
    "positive": ("rgba(8, 127, 91, 0.12)", _COLOR_POSITIVE),
    "danger": ("rgba(194, 65, 77, 0.12)", _COLOR_NEGATIVE),
}


def _badge(text: str, variant: str = "accent") -> str:
    bg, fg = _BADGE_VARIANTS.get(variant, _BADGE_VARIANTS["accent"])
    return (
        f'<div style="display:inline-block;background:{bg};color:{fg};font-family:{_FONT};'
        f'font-size:12px;font-weight:600;padding:5px 12px;border-radius:999px;">{text}</div>'
    )


def _heading(text: str) -> str:
    return (
        f'<h1 style="font-family:{_FONT};font-size:23px;line-height:1.3;font-weight:700;'
        f'color:{_COLOR_INK};margin:16px 0 10px;">{text}</h1>'
    )


def _para(text: str) -> str:
    return (
        f'<p style="font-family:{_FONT};font-size:15px;line-height:1.65;'
        f'color:{_COLOR_INK_SOFT};margin:0 0 16px;">{text}</p>'
    )


def _hint(text: str) -> str:
    return (
        f'<p style="font-family:{_FONT};font-size:13px;line-height:1.6;'
        f'color:{_COLOR_SUBTLE};margin:6px 0 0;">{text}</p>'
    )


def _detail_card(rows: list[tuple[str, str, str]]) -> str:
    """A light bordered card of label/value rows.

    Each row is ``(label, value, value_color)`` — value_color is a hex string
    (use the semantic colours for amounts) or empty for the default ink.
    """
    cells = []
    for index, (label, value, value_color) in enumerate(rows):
        top = f"border-top:1px solid {_COLOR_BORDER};" if index else ""
        color = value_color or _COLOR_INK
        cells.append(
            f'<tr><td style="font-family:{_FONT};font-size:14px;color:{_COLOR_INK_SOFT};'
            f'padding:9px 0;{top}">{label}</td>'
            f'<td align="right" style="font-family:{_FONT};font-size:14px;font-weight:600;'
            f'color:{color};padding:9px 0;{top}white-space:nowrap;">{value}</td></tr>'
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{_COLOR_SURFACE};border-radius:12px;">'
        f'<tr><td style="padding:6px 20px;">'
        f'<table role="presentation" width="100%">{"".join(cells)}</table>'
        f"</td></tr></table>"
    )


def _fallback_link(url: str) -> str:
    return (
        f'<div style="border-top:1px solid {_COLOR_BORDER};margin:24px 0 0;padding:16px 0 0;">'
        f'<p style="font-family:{_FONT};font-size:12px;line-height:1.6;color:{_COLOR_SUBTLE};margin:0;">'
        f"Se o botão não funcionar, copie e cole este link no navegador:<br/>"
        f'<a href="{url}" style="color:{_COLOR_BRAND};word-break:break-all;">{url}</a></p></div>'
    )


# ---------------------------------------------------------------------------
# Base layout
# ---------------------------------------------------------------------------


def _base_layout(
    *, title: str, preview_text: str, body_html: str, eyebrow: str = ""
) -> str:
    """Wrap the email body in the Auraxis branded (light) shell.

    Table-based for maximum client compatibility. The header is a teal→green
    brand gradient with the Auraxis wordmark and an optional ``eyebrow``.
    """
    eyebrow_html = (
        f'<td align="right" style="font-family:{_FONT};font-size:12px;'
        f'color:rgba(255,255,255,0.82);">{eyebrow}</td>'
        if eyebrow
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <title>{title}</title>
  <!--[if mso]>
  <noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript>
  <![endif]-->
  <style>
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    img {{ -ms-interpolation-mode: bicubic; border: 0; height: auto; line-height: 100%; outline: none; text-decoration: none; }}
    body {{ margin: 0; padding: 0; background-color: {_COLOR_BG}; }}
    .email-container {{ max-width: 600px; margin: 0 auto; }}
    @media only screen and (max-width: 600px) {{
      .email-container {{ width: 100% !important; }}
      .email-body {{ padding: 28px 22px !important; }}
    }}
  </style>
</head>
<body>
  <div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{preview_text}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;</div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="background-color:{_COLOR_BG};">
    <tr>
      <td align="center" style="padding: 28px 14px;">
        <table role="presentation" class="email-container" cellpadding="0" cellspacing="0" border="0" width="600"
               style="background-color:{_COLOR_CARD};border-radius:16px;overflow:hidden;box-shadow:0 6px 24px rgba(10,22,40,0.08);">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,{_COLOR_BRAND},{_COLOR_GREEN});padding:22px 32px;">
              <table role="presentation" width="100%"><tr>
                <td style="font-family:{_FONT};font-size:20px;font-weight:700;letter-spacing:-0.02em;color:#ffffff;">Auraxis</td>
                {eyebrow_html}
              </tr></table>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td class="email-body" style="padding: 32px 32px 8px;">
              {body_html}
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding: 24px 32px; border-top: 1px solid {_COLOR_SURFACE};">
              <p style="font-family:{_FONT};font-size:12px;line-height:1.6;color:{_COLOR_SUBTLE};margin:0;">
                Email automático da Auraxis — por favor não responda.
                &copy; 2026 Auraxis &bull;
                <a href="{web_base_url()}" style="color:{_COLOR_SUBTLE};text-decoration:underline;">app.auraxis.com.br</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Signature helper
# ---------------------------------------------------------------------------

_SIGNATURE = "— Equipe Auraxis\nhttps://app.auraxis.com.br\n"


# ---------------------------------------------------------------------------
# Auth emails
# ---------------------------------------------------------------------------


def render_confirmation_email(*, confirmation_url: str) -> tuple[str, str]:
    """Render the account confirmation email."""
    body_html = (
        _badge("Bem-vindo à Auraxis", "positive")
        + _heading("Confirme seu email para começar")
        + _para(
            "Olá! Falta só um passo para você assumir o controle das suas "
            "finanças. Confirme seu email no botão abaixo e sua conta é ativada "
            "na hora."
        )
        + _button(confirmation_url, "Confirmar meu email →")
        + _hint("O botão ativa sua conta. O link vale por 24 horas.")
        + _para(
            "Se você não criou uma conta na Auraxis, é só ignorar este email — "
            "nada acontece."
        )
        + _fallback_link(confirmation_url)
    )
    html = _base_layout(
        title="Confirme sua conta Auraxis",
        preview_text="Confirme seu email para ativar sua conta Auraxis.",
        body_html=body_html,
        eyebrow="Ativação de conta",
    )
    text = (
        "Confirme seu email para começar\n\n"
        "Falta só um passo para assumir o controle das suas finanças. Confirme "
        "seu email no link abaixo e sua conta é ativada na hora:\n\n"
        f"{confirmation_url}\n\n"
        "O link vale por 24 horas. Se você não criou uma conta na Auraxis, "
        "ignore este email.\n\n" + _SIGNATURE
    )
    return html, text


def render_password_reset_email(*, reset_url: str) -> tuple[str, str]:
    """Render the password reset email."""
    body_html = (
        _badge("Segurança", "accent")
        + _heading("Vamos redefinir sua senha")
        + _para(
            "Recebemos um pedido para redefinir a senha da sua conta. Clique no "
            "botão abaixo para criar uma nova — leva menos de um minuto."
        )
        + _button(reset_url, "Criar nova senha →")
        + _hint("O link vale por 1 hora, por segurança.")
        + _para(
            "Não foi você? Pode ignorar este email com tranquilidade — sua senha "
            "atual continua valendo e sua conta segue protegida."
        )
        + _fallback_link(reset_url)
    )
    html = _base_layout(
        title="Redefinir senha — Auraxis",
        preview_text="Pedido de redefinição de senha da sua conta Auraxis.",
        body_html=body_html,
        eyebrow="Redefinição de senha",
    )
    text = (
        "Vamos redefinir sua senha\n\n"
        "Recebemos um pedido para redefinir a senha da sua conta. Use o link "
        "abaixo para criar uma nova (vale por 1 hora):\n\n"
        f"{reset_url}\n\n"
        "Não foi você? Ignore este email — sua senha atual continua valendo.\n\n"
        + _SIGNATURE
    )
    return html, text


def render_account_deletion_email() -> tuple[str, str]:
    """Render the LGPD account deletion confirmation email."""
    body_html = (
        _heading("Sua conta foi excluída")
        + _para(
            "Confirmamos que sua conta Auraxis foi excluída. Todos os seus dados "
            "pessoais foram anonimizados conforme a "
            "<strong>Lei Geral de Proteção de Dados (LGPD)</strong>."
        )
        + _para(
            "Não foi você que pediu a exclusão, ou acha que houve engano? Fale "
            "com o nosso suporte o quanto antes."
        )
        + _hint(
            "Obrigado por ter usado a Auraxis. Torcemos para ter ajudado a "
            "cuidar melhor do seu dinheiro."
        )
    )
    html = _base_layout(
        title="Conta excluída — Auraxis",
        preview_text="Sua conta Auraxis foi excluída (LGPD).",
        body_html=body_html,
        eyebrow="Privacidade",
    )
    text = (
        "Sua conta foi excluída\n\n"
        "Confirmamos que sua conta Auraxis foi excluída. Todos os seus dados "
        "pessoais foram anonimizados conforme a LGPD.\n\n"
        "Não foi você, ou acha que houve engano? Fale com o suporte o quanto "
        "antes.\n\nObrigado por ter usado a Auraxis.\n\n" + _SIGNATURE
    )
    return html, text


# ---------------------------------------------------------------------------
# Transaction reminder
# ---------------------------------------------------------------------------


def render_due_soon_email(
    *,
    title: str,
    amount_formatted: str,
    days_before_due: int,
    due_date_label: str = "",
    transaction_url: str | None = None,
) -> tuple[str, str]:
    """Render the transaction due-soon reminder (D-7 or D-1).

    When ``transaction_url`` is provided the CTA deep-links straight to that
    transaction; otherwise it falls back to the transactions list.
    """
    link = transaction_url or f"{web_base_url()}/transactions"
    if days_before_due == 1:
        when = "amanhã"
        badge = _badge("⏳ Vence amanhã", "warning")
        heading = "Uma conta sua está quase vencendo"
    else:
        when = f"em {days_before_due} dias"
        badge = _badge(f"⏳ Vence em {days_before_due} dias", "warning")
        heading = "Uma conta sua está chegando no vencimento"

    due_suffix = f" ({due_date_label})" if due_date_label else ""
    rows = [
        (title, f"R$ {amount_formatted}", _COLOR_NEGATIVE),
        ("Vencimento", (due_date_label or when).capitalize(), ""),
    ]
    body_html = (
        badge
        + _heading(heading)
        + _para(
            f"Passando só para lembrar de um pagamento que vence <strong>{when}"
            f"{due_suffix}</strong>. Dá para resolver em segundos."
        )
        + _detail_card(rows)
        + _button(link, "Ver transação →")
        + _hint("O botão abre exatamente essa transação no seu Auraxis.")
    )
    email_title = (
        "Amanhã vence uma conta sua"
        if days_before_due == 1
        else f"Uma conta vence em {days_before_due} dias"
    )
    html = _base_layout(
        title=email_title,
        preview_text=f"{title} — R$ {amount_formatted}, vence {when}.",
        body_html=body_html,
        eyebrow="Lembrete de vencimento",
    )
    text = (
        f"{heading}\n\n"
        f"'{title}' vence {when}{due_suffix}, no valor de R$ {amount_formatted}.\n\n"
        f"Ver a transação: {link}\n\n"
        "Você recebe este lembrete porque ativou avisos de vencimento — ajuste "
        "quando quiser nas configurações.\n\n" + _SIGNATURE
    )
    return html, text


# ---------------------------------------------------------------------------
# AI insight emails
# ---------------------------------------------------------------------------


def _insight_items(items: list[tuple[str, str]]) -> str:
    """A card listing the insight's items as ``(title, message)`` blocks.

    Unlike :func:`_detail_card` (label/value pairs, right-aligned amounts),
    each entry here is a short paragraph: a bold title with the analysis text
    underneath. Content comes from the LLM, so it is HTML-escaped.
    """
    blocks = []
    for index, (title, message) in enumerate(items):
        top = f"border-top:1px solid {_COLOR_BORDER};" if index else ""
        blocks.append(
            f'<tr><td style="padding:14px 0;{top}">'
            f'<p style="font-family:{_FONT};font-size:14px;font-weight:600;'
            f'color:{_COLOR_INK};margin:0 0 4px;">{escape(title)}</p>'
            f'<p style="font-family:{_FONT};font-size:14px;line-height:1.6;'
            f'color:{_COLOR_INK_SOFT};margin:0;">{escape(message)}</p>'
            f"</td></tr>"
        )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:{_COLOR_SURFACE};border-radius:12px;margin:20px 0 0;">'
        f'<tr><td style="padding:2px 20px;">'
        f'<table role="presentation" width="100%">{"".join(blocks)}</table>'
        f"</td></tr></table>"
    )


def _insight_items_text(items: list[tuple[str, str]]) -> str:
    """Plain-text counterpart of :func:`_insight_items`."""
    return "".join(f"- {title}: {message}\n" for title, message in items)


def _insight_body(
    *,
    eyebrow_badge: str,
    heading: str,
    intro: str,
    items: list[tuple[str, str]] | None,
    suggestion: str,
    cta_url: str,
    cta_label: str,
    cta_hint: str,
) -> str:
    parts = [_badge(eyebrow_badge, "accent"), _heading(heading), _para(intro)]
    if items:
        parts.append(_insight_items(items))
    if suggestion:
        parts.append(
            f'<p style="font-family:{_FONT};font-size:14px;line-height:1.6;'
            f'color:{_COLOR_INK_SOFT};margin:16px 0 0;">'
            f'<strong style="color:{_COLOR_GREEN};">Sugestão:</strong> '
            f"{escape(suggestion)}</p>"
        )
    parts.append(_button(cta_url, cta_label))
    parts.append(_hint(cta_hint))
    return "".join(parts)


def render_analysis_ready_email(
    *,
    first_name: str,
    summary_preview: str,
    insight_url: str | None = None,
    items: list[tuple[str, str]] | None = None,
    suggestion: str = "",
) -> tuple[str, str]:
    """Render the weekly 'AI analysis ready' email.

    When ``insight_url`` is given the CTA deep-links to that insight; when
    ``items`` is given the full insight is embedded in the email (#1617).
    """
    cta_url = insight_url or f"{web_base_url()}/insights"
    body_html = _insight_body(
        eyebrow_badge="✨ Insight de gastos",
        heading=f"{first_name}, seu insight da semana está pronto",
        intro=summary_preview,
        items=items,
        suggestion=suggestion,
        cta_url=cta_url,
        cta_label="Abrir no Auraxis →",
        cta_hint="O botão leva para /insights com este insight já aberto.",
    )
    html = _base_layout(
        title=f"Seu insight da semana, {first_name}",
        preview_text="Seu insight financeiro da semana já está no Auraxis.",
        body_html=body_html,
        eyebrow="Seu insight da semana",
    )
    text = (
        f"{first_name}, seu insight da semana está pronto\n\n"
        f"{summary_preview}\n\n"
        + (_insight_items_text(items) + "\n" if items else "")
        + (f"Sugestão: {suggestion}\n\n" if suggestion else "")
        + f"Abrir no Auraxis: {cta_url}\n\n"
        + "Gerado pela IA da Auraxis a partir das suas transações — sem "
        "julgamentos, só clareza.\n\n" + _SIGNATURE
    )
    return html, text


def render_monthly_analysis_ready_email(
    *,
    first_name: str,
    summary_preview: str,
    insight_url: str,
    items: list[tuple[str, str]] | None = None,
    suggestion: str = "",
) -> tuple[str, str]:
    """Render the monthly AI report email with a deep link + embedded insight."""
    body_html = _insight_body(
        eyebrow_badge="📊 Relatório mensal",
        heading=f"{first_name}, seu resumo do mês chegou",
        intro=summary_preview,
        items=items,
        suggestion=suggestion,
        cta_url=insight_url,
        cta_label="Abrir relatório completo →",
        cta_hint="O botão leva para /insights com o relatório do mês já aberto.",
    )
    html = _base_layout(
        title=f"Seu resumo do mês, {first_name}",
        preview_text="Seu consolidado mensal de finanças já está no Auraxis.",
        body_html=body_html + _fallback_link(insight_url),
        eyebrow="Resumo do mês",
    )
    text = (
        f"{first_name}, seu resumo do mês chegou\n\n"
        f"{summary_preview}\n\n"
        + (_insight_items_text(items) + "\n" if items else "")
        + (f"Sugestão: {suggestion}\n\n" if suggestion else "")
        + f"Abrir relatório completo: {insight_url}\n\n"
        + _SIGNATURE
    )
    return html, text


# ---------------------------------------------------------------------------
# Email verification reminder
# ---------------------------------------------------------------------------


def render_email_verification_reminder_email(
    *, days_until_deadline: int
) -> tuple[str, str]:
    """Render the D-7 / D-1 verification reminder email."""
    resend_url = f"{web_base_url()}/resend-confirmation"
    if days_until_deadline == 1:
        email_title = "Último dia para confirmar seu email"
        preview = "Amanhã sua conta fica só-leitura. Confirme para manter o acesso."
        heading = "Último dia para confirmar seu email"
        intro = (
            "Sua conta foi criada há quase 14 dias. Se o email não for confirmado "
            "<strong>até amanhã</strong>, ela entra em modo só-leitura: você ainda "
            "vê seus dados, mas não consegue criar ou editar nada."
        )
        cta_label = "Confirmar agora →"
    else:
        email_title = f"Faltam {days_until_deadline} dias para confirmar seu email"
        preview = (
            f"Confirme seu email em {days_until_deadline} dias para não perder "
            "acesso a novas transações."
        )
        heading = f"Faltam {days_until_deadline} dias para confirmar seu email"
        intro = (
            "Você criou sua conta na Auraxis há pouco, mas ainda não confirmou o "
            f"email. Em <strong>{days_until_deadline} dias</strong> ela entra em "
            "modo só-leitura se o email não for confirmado."
        )
        cta_label = "Confirmar email →"

    body_html = (
        _badge("Confirmação pendente", "warning")
        + _heading(heading)
        + _para(intro)
        + _button(resend_url, cta_label)
        + _hint("O botão reenvia seu email de confirmação em segundos.")
    )
    html = _base_layout(
        title=email_title,
        preview_text=preview,
        body_html=body_html,
        eyebrow="Confirmação de email",
    )
    text = (
        f"{heading}\n\n"
        + intro.replace("<strong>", "").replace("</strong>", "")
        + f"\n\nConfirmar agora: {resend_url}\n\n"
        + _SIGNATURE
    )
    return html, text


# ---------------------------------------------------------------------------
# Billing emails (migrated into the shared layout — #emails redesign)
# ---------------------------------------------------------------------------


def render_billing_payment_confirmed_email(*, plan_label: str) -> tuple[str, str]:
    body_html = (
        _badge("Pagamento confirmado", "positive")
        + _heading("Tudo certo com seu pagamento")
        + _para(
            "Seu pagamento foi confirmado e o acesso premium está ativo. "
            f"Plano ativo: <strong>{plan_label}</strong>."
        )
        + _button(f"{web_base_url()}/dashboard", "Ir para o Auraxis →")
    )
    html = _base_layout(
        title="Pagamento confirmado na Auraxis",
        preview_text="Seu pagamento foi confirmado e o premium está ativo.",
        body_html=body_html,
        eyebrow="Cobrança",
    )
    text = (
        "Tudo certo com seu pagamento\n\n"
        f"Seu pagamento foi confirmado e o acesso premium está ativo. Plano "
        f"ativo: {plan_label}.\n\n" + _SIGNATURE
    )
    return html, text


def render_billing_payment_failed_email(*, plan_label: str) -> tuple[str, str]:
    body_html = (
        _badge("Pagamento pendente", "warning")
        + _heading("Não conseguimos confirmar seu pagamento")
        + _para(
            "Houve uma pendência na cobrança da sua assinatura. Sem stress: você "
            "tem alguns dias de tolerância antes de qualquer mudança, e o "
            f"premium continua ativo enquanto isso. Plano: <strong>{plan_label}</strong>."
        )
        + _button(f"{web_base_url()}/dashboard", "Revisar assinatura →")
    )
    html = _base_layout(
        title="Pagamento pendente na Auraxis",
        preview_text="Houve uma pendência no pagamento da sua assinatura.",
        body_html=body_html,
        eyebrow="Cobrança",
    )
    text = (
        "Não conseguimos confirmar seu pagamento\n\n"
        "Houve uma pendência na cobrança da sua assinatura. Você tem alguns dias "
        "de tolerância antes de qualquer mudança, e o premium continua ativo "
        f"enquanto isso. Plano: {plan_label}.\n\n" + _SIGNATURE
    )
    return html, text


def render_billing_refund_email(*, plan_label: str) -> tuple[str, str]:
    body_html = (
        _badge("Estorno processado", "danger")
        + _heading("Seu estorno foi processado")
        + _para(
            "Um estorno foi processado e, com ele, o acesso premium foi "
            f"encerrado. Plano encerrado: <strong>{plan_label}</strong>."
        )
        + _para("Quando quiser voltar, é só assinar de novo — leva um minuto.")
        + _button(f"{web_base_url()}/dashboard", "Ver planos →")
    )
    html = _base_layout(
        title="Estorno processado — Auraxis",
        preview_text="Um estorno foi processado e o premium foi encerrado.",
        body_html=body_html,
        eyebrow="Cobrança",
    )
    text = (
        "Seu estorno foi processado\n\n"
        "Um estorno foi processado e o acesso premium foi encerrado. Plano "
        f"encerrado: {plan_label}. Quando quiser voltar, é só assinar de "
        "novo.\n\n" + _SIGNATURE
    )
    return html, text


def render_billing_canceled_email(*, plan_label: str) -> tuple[str, str]:
    body_html = (
        _badge("Assinatura cancelada", "accent")
        + _heading("Sua assinatura foi cancelada")
        + _para(
            "Confirmamos o cancelamento da sua assinatura. Plano anterior: "
            f"<strong>{plan_label}</strong>. Você continua com a conta e os seus "
            "dados — só sem os recursos premium."
        )
        + _para("Mudou de ideia? Dá para reativar quando quiser.")
        + _button(f"{web_base_url()}/dashboard", "Reativar premium →")
    )
    html = _base_layout(
        title="Assinatura cancelada na Auraxis",
        preview_text="Sua assinatura foi cancelada.",
        body_html=body_html,
        eyebrow="Cobrança",
    )
    text = (
        "Sua assinatura foi cancelada\n\n"
        f"Confirmamos o cancelamento. Plano anterior: {plan_label}. Você continua "
        "com a conta e os seus dados — só sem os recursos premium. Dá para "
        "reativar quando quiser.\n\n" + _SIGNATURE
    )
    return html, text


def render_billing_trial_ending_email(
    *, days_label: str, trial_ends_label: str | None
) -> tuple[str, str]:
    ends = f" Ele termina em {trial_ends_label}." if trial_ends_label else ""
    body_html = (
        _badge("Seu teste está acabando", "warning")
        + _heading(f"Seu período de teste termina em {days_label}")
        + _para(
            f"Seu teste gratuito da Auraxis termina em <strong>{days_label}</strong>."
            f"{ends} Assine para continuar com os recursos premium — exportação em "
            "PDF, simulações avançadas e mais."
        )
        + _button(f"{web_base_url()}/dashboard", "Assinar e continuar →")
    )
    html = _base_layout(
        title=f"Seu teste termina em {days_label} — Auraxis",
        preview_text=f"Seu teste gratuito termina em {days_label}.",
        body_html=body_html,
        eyebrow="Período de teste",
    )
    text = (
        f"Seu período de teste termina em {days_label}\n\n"
        f"Seu teste gratuito da Auraxis termina em {days_label}.{ends} Assine para "
        "continuar com os recursos premium.\n\n" + _SIGNATURE
    )
    return html, text


def render_billing_trial_expired_email(*, plan_label: str) -> tuple[str, str]:
    body_html = (
        _badge("Teste encerrado", "accent")
        + _heading("Seu período de teste terminou")
        + _para(
            "Seu teste gratuito acabou e sua conta voltou para o plano "
            f"<strong>{plan_label}</strong>. Você continua com todos os seus "
            "dados salvos."
        )
        + _para("Quando quiser recuperar o premium, é só assinar.")
        + _button(f"{web_base_url()}/dashboard", "Recuperar premium →")
    )
    html = _base_layout(
        title="Seu período de teste terminou — Auraxis",
        preview_text="Seu teste terminou e sua conta voltou ao plano gratuito.",
        body_html=body_html,
        eyebrow="Período de teste",
    )
    text = (
        "Seu período de teste terminou\n\n"
        f"Seu teste gratuito acabou e sua conta voltou para o plano {plan_label}. "
        "Seus dados continuam salvos. Quando quiser recuperar o premium, é só "
        "assinar.\n\n" + _SIGNATURE
    )
    return html, text


def render_billing_grace_expired_email(*, plan_label: str) -> tuple[str, str]:
    body_html = (
        _badge("Assinatura encerrada", "danger")
        + _heading("Não recebemos o pagamento a tempo")
        + _para(
            "Não conseguimos confirmar o pagamento dentro do período de "
            "tolerância, então o acesso premium foi encerrado. Plano encerrado: "
            f"<strong>{plan_label}</strong>."
        )
        + _para("Regularize o pagamento para reativar quando quiser.")
        + _button(f"{web_base_url()}/dashboard", "Regularizar e reativar →")
    )
    html = _base_layout(
        title="Assinatura encerrada por falta de pagamento — Auraxis",
        preview_text="O período de tolerância acabou e o premium foi encerrado.",
        body_html=body_html,
        eyebrow="Cobrança",
    )
    text = (
        "Não recebemos o pagamento a tempo\n\n"
        "Não conseguimos confirmar o pagamento dentro do período de tolerância, "
        f"então o acesso premium foi encerrado. Plano encerrado: {plan_label}. "
        "Regularize o pagamento para reativar quando quiser.\n\n" + _SIGNATURE
    )
    return html, text


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
