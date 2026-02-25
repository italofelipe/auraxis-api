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

## Observação

Este gate valida apenas governança/lifecycle da flag.
A integração runtime com provider OSS permanece no escopo do PLT4 principal.
