# PLT4.1 - Feature Flags Hygiene (API)

## Objetivo

Bloquear no CI qualquer flag sem metadados obrigatórios ou com expiração vencida sem cleanup.

## Entregas

1. Catálogo versionado:
   - `config/feature-flags.json`
2. Validador:
   - `scripts/check_feature_flags.py`
3. Gate no CI:
   - step `Feature Flags Hygiene` em `.github/workflows/ci.yml` (job `quality`)
4. Paridade local:
   - etapa `flags:hygiene` em `scripts/run_ci_like_actions_local.sh`

## Regras validadas

- `owner` obrigatório.
- `createdAt` e `removeBy` obrigatórios em formato `YYYY-MM-DD`.
- `removeBy` não pode ser anterior a `createdAt`.
- flag com `removeBy` no passado deve estar `status=removed`.
- `key` deve começar com prefixo `api.` e não pode duplicar.

## PLT4.2 (runtime OSS) — entregue

Integração runtime adicionada em:

- `app/utils/feature_flags.py`

Modelo de resolução efetiva:

1. `provider_value` explícito (quando informado);
2. decisão remota de provider (`unleash`);
3. override de ambiente (`AURAXIS_FEATURE_FLAGS`);
4. fallback para catálogo local (`config/feature-flags.json`).

Variáveis de ambiente suportadas (API):

- `AURAXIS_FLAG_PROVIDER` (`local` | `unleash`, default `local`)
- `AURAXIS_UNLEASH_URL` (endpoint base do provider)
- `AURAXIS_UNLEASH_API_TOKEN` (token de cliente, opcional)
- `AURAXIS_UNLEASH_APP_NAME` (default `auraxis-api`)
- `AURAXIS_UNLEASH_INSTANCE_ID` (default `auraxis-api`)
- `AURAXIS_UNLEASH_ENVIRONMENT` (default `development`)
- `AURAXIS_UNLEASH_TIMEOUT_SECONDS` (default `2`)
- `AURAXIS_UNLEASH_CACHE_TTL_SECONDS` (default `30`)
