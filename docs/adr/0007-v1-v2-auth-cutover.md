# ADR 0007 — Estratégia de cutover de auth v1 (Flask) → v2 (FastAPI)

**Status:** Aceito · **Data:** 2026-07-05 · Relacionado: F2 social login, faxina de robustez (#1539)

## Contexto

Existem dois backends: `auraxis-api` (Flask v1, produção atual) e `auraxis-api-v2`
(FastAPI, em construção). O login social (F2) é **"puro v2"** — nasce no FastAPI, sem
Flask. Os dois backends **compartilham `JWT_SECRET_KEY`** e algoritmo, então os access
tokens são **interoperáveis** (um token emitido pelo v2 é aceito pelo v1 e vice-versa,
enquanto o claim shape for compatível).

Risco: sem uma estratégia explícita de cutover, os clientes (web/app) podem acabar
falando com endpoints de auth divergentes (v1 vs v2) sem contrato unificado, e um
usuário criado só no v2 (social) pode não conseguir usar features ainda servidas pelo v1.

## Decisão

1. **Tokens compartilhados durante a transição.** v1 e v2 mantêm o MESMO
   `JWT_SECRET_KEY` e o mesmo formato de claims essenciais (`sub`, `jti`, `csrf`,
   expiração) para que access tokens sejam aceitos pelos dois. Qualquer mudança de
   claim shape exige atualizar os dois lados na mesma janela.
2. **Cookies com domínio pai.** `JWT_COOKIE_DOMAIN=.auraxis.com.br` nos dois backends,
   para que o refresh/CSRF cookie seja legível cross-subdomínio (`api.` ↔ `app.`).
   (Ver incidente 2026-07-03 e validação de env obrigatório no deploy.)
3. **Cutover por domínio de feature, não big-bang.** Cada domínio migra do v1 para o v2
   individualmente; enquanto migra, o v1 continua servindo. O web/app selecionam a base
   por feature (`apiBase` v1 vs `apiV2Base`) até o domínio estar 100% no v2.
4. **Usuário social (v2) e acesso a features v1.** Consequência aceita: um usuário
   criado só via social (v2) só acessa features já migradas para o v2 até a migração de
   auth completar. Isso é explícito no roadmap (F2).
5. **Sem duplicar contrato.** Endpoints migrados seguem o envelope unificado (ADR 0008)
   e mantêm paridade REST/GraphQL (gate `scripts/check-rest-graphql-parity.sh`).

## Consequências

- **Positivo:** migração incremental e reversível; nenhum big-bang; tokens
  interoperáveis evitam re-login em massa durante a transição.
- **Negativo/aceito:** janela em que usuários social-only têm acesso parcial; disciplina
  necessária para manter claim shape + cookie config sincronizados entre v1 e v2.
- **Follow-up:** quando um domínio migra 100%, remover o endpoint v1 correspondente e
  atualizar o snapshot OpenAPI.
