# PLT3 - Versioning Foundation (API)

## Objetivo

Eliminar versionamento manual e padronizar releases da API com base em Conventional Commits.

## Entrega deste bloco

- `.github/workflows/release-please.yml`
- `.release-please-config.json`
- `.release-please-manifest.json`

## Como funciona

1. Push em `master/main` dispara `Release Please`.
2. A action abre/atualiza PR de release com changelog e versão semântica.
3. Ao mergear o PR de release:
   - tag semântica é criada;
   - release GitHub é publicada automaticamente.

## Observações

- Estratégia da API está em `release-type: simple`:
  - source of truth da versão é a tag/release no Git;
  - não há bump automático de arquivo Python neste bloco.
- Para sincronizar versão em runtime (ex.: endpoint `/version`), criar task dedicada para injetar tag de release em build/deploy.
