# Manifesto de env de produção

Fonte canônica das variáveis de ambiente de **produção**. O `.env.prod` real (no host,
`/opt/auraxis/.env.prod`) **não** é versionado — este manifesto + `.env.prod.example`
são a fonte da verdade. O deploy (`scripts/aws_deploy_i6.py`) valida as chaves
**obrigatórias** e **avisa** sobre as recomendadas ausentes.

> Motivação: em 2026-07-03 o drift de `JWT_COOKIE_DOMAIN` (ausente no `.env.prod`)
> quebrou o F5 silenciosamente — o deploy passava "healthy" com auth quebrada.
> Ver `docs/wiki/INF-incident-env-drift.md` (platform).

## Obrigatórias (deploy **bloqueia** se ausentes)

| Chave | Por quê |
|-------|---------|
| `SECRET_KEY`, `JWT_SECRET_KEY` | Assinatura de sessão/JWT (força validada ≥32 chars). |
| `DOMAIN`, `CERTBOT_EMAIL` (prod) | TLS/nginx. |
| `POSTGRES_DB/USER/PASSWORD`, `DB_HOST/PORT/NAME/USER/PASS` | Banco. |
| `RATE_LIMIT_*`, `LOGIN_GUARD_*` | Rate limit / brute-force guard (fail-closed). |
| **`JWT_COOKIE_DOMAIN`** | **Cookie CSRF cross-subdomínio.** Ausente → F5 desloga (incidente 2026-07-03). |
| **`CORS_ALLOWED_ORIGINS`** | CORS com credentials; ausente/errado bloqueia o refresh. |
| **`AURAXIS_CSRF_ENFORCE`** | Liga o double-submit CSRF; acopla com `JWT_COOKIE_DOMAIN`. |

## Recomendadas (deploy **avisa**, não bloqueia)

| Chave | Impacto se ausente |
|-------|--------------------|
| `SENTRY_DSN` | Sem observabilidade de erros. |
| `EMAIL_PROVIDER`, `EMAIL_FROM` | Emails (confirmação, recap) silenciosamente não saem. |
| `BILLING_PROVIDER`, `BILLING_ASAAS_*` | Checkout/assinatura quebra. |
| `BILLING_ABACATEPAY_API_KEY`, `BILLING_ABACATEPAY_PRODUCT_*` | Checkout do AbacatePay quebra (produto carrega preco e ciclo). |
| `BILLING_ABACATEPAY_WEBHOOK_SECRET` | Webhooks do AbacatePay rejeitados — assinatura nunca ativa apos pagamento. |
| `JWT_COOKIE_SAMESITE` | Default `Lax` no config; explicitar em prod é preferível. |

## Regras
- Ao adicionar env crítica nova: registrar aqui + em `.env.prod.example` + na validação
  de `aws_deploy_i6.py` (obrigatória) ou no loop de warn (recomendada).
- Recreate/deploy sempre via `scripts/deploy-prod.sh` ou o fluxo `aws_deploy_i6.py`
  (skill `auraxis:prod-deploy`). Nunca `docker compose` pelado (ver `INF-incident-image-stale.md`).
