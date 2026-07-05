# ADR 0008 — Envelope unificado REST/GraphQL + gate de paridade

**Status:** Aceito (alvo) · **Data:** 2026-07-05 · Relacionado: ADR 0002 (ownership), faxina (#1535)

## Contexto

Hoje as respostas divergem por protocolo:

- **REST** (controllers Flask) usa o envelope `_compat_success` →
  `{ "message": "...", "data": { ... } }` (e `_compat_error` com `error_code`).
- **GraphQL** (Graphene) retorna os tipos diretamente, **sem** envelope.

O cliente web precisa suportar múltiplas formas (ex.: desembrulhar `data.items` /
`data.transaction` / cru), o que é frágil: uma mudança de forma no backend quebra o
parsing silenciosamente. Não há contrato formal de envelope nem gate garantindo que toda
feature exponha **REST e GraphQL** (regra do projeto).

## Decisão (alvo)

1. **Envelope de sucesso canônico (REST):** `{ "message", "data" }` — mantém o
   `_compat_success` atual como fonte. GraphQL continua retornando o tipo tipado
   (o "envelope" do GraphQL é o próprio `data.<campo>` da spec), mas os **nomes de campo
   e shapes de domínio** devem ser idênticos aos do REST.
2. **Envelope de erro canônico:** `{ "message", "error_code" }` no REST; no GraphQL, o
   mesmo `error_code` vai em `extensions.code` do erro. Um cliente deve conseguir mapear
   `error_code` de forma uniforme entre os dois.
3. **Paridade obrigatória:** toda query de dados exposta em REST tem equivalente GraphQL
   (ADR 0002). Um gate advisory (`scripts/check-rest-graphql-parity.sh`) lista lacunas.
4. **NÃO-breaking:** este ADR fixa o **alvo**; migração de endpoints legados para o
   envelope canônico é incremental e feita endpoint a endpoint (nunca muda o envelope de
   um endpoint já consumido em produção sem versionar/coordenar com o cliente).

## Consequências

- **Positivo:** cliente para de adivinhar shapes; contrato explícito; gate torna lacunas
  de paridade visíveis.
- **Negativo/aceito:** endpoints legados só convergem gradualmente; o gate começa
  **advisory** (não bloqueia) para não quebrar o CI enquanto a paridade não é 100%.
- **Follow-up:** promover o gate de advisory → bloqueante quando a paridade atingir o
  alvo; adicionar teste de contrato que trave o shape do envelope por domínio.
