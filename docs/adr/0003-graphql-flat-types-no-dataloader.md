# ADR-0003 — GraphQL flat types + service-layer batching, no DataLoader

**Status:** Accepted (2026-05-02)

**Contexto:** auditoria de 2026-05-01 sinalizou ausência total de
`aiodataloader` no `auraxis-api/app/graphql/` como risco de N+1
(13 query types + 11 mutation types). Investigação subsequente
mostrou que a ausência é deliberada e o risco apontado não se
materializa nesta arquitetura.

## Decisão

A camada GraphQL deste API:

1. **Não usa DataLoader.**
2. **Não tem field-level resolvers em ObjectTypes.** Todos os tipos
   (`TransactionTypeObject`, `GoalTypeObject`, `UserType`, etc.)
   declaram apenas escalares (`graphene.String`, `Int`, `ID`,
   `Boolean`, etc.) e listas tipadas pré-computadas pelo resolver
   raiz.
3. **Eager loading vive nos services.** Os 14 sítios atuais que
   chamam `joinedload` / `selectinload` ficam em
   `app/services/*.py` (`budget_service`, `portfolio_*_service`,
   `shared_entry_service`, etc.). Cada serviço é responsável por
   buscar relations relevantes em uma única query SQL.
4. **Resolvers raiz são thin adapters.** Pegam o user via
   `get_current_user_required()`, instanciam o
   `<Domain>QueryService.with_defaults(user.id)`, chamam o método
   apropriado, e mapeiam o retorno (já completo, com relações
   resolvidas) para o tipo Graphene.

## Por quê

- **Performance previsível.** Cada query GraphQL hit conhecido =
  N consultas SQL conhecidas. Sem campos nested derivados.
- **Service layer é a fonte de verdade.** A mesma lógica de
  eager-load atende REST, GraphQL e qualquer outro consumer
  futuro. Sem duplicação.
- **DataLoader exigiria nested resolvers.** Para introduzir
  DataLoader, precisaríamos primeiro adicionar campos como
  `TransactionTypeObject.account` (um `graphene.Field(AccountType)`
  com resolver custom). Isso é uma decisão arquitetural que não
  foi tomada — o trade-off (riqueza de queries aninhadas vs
  custo de field resolvers) favorece tipos flat para o produto
  atual.
- **Schema migration cost.** Adotar campos nested + DataLoader
  numa schema flat existente é refactor amplo (toda query atual
  precisa repensar a forma) sem benefício imediato — clientes
  consomem dados flat hoje.

## Quando reconsiderar

Reabrir esta ADR quando algum dos abaixo for verdade:

1. **Cliente pedir queries fortemente aninhadas** (ex.: dashboard
   que precisa de `user { transactions { account { name } } }`
   em uma única round-trip). Hoje o web/app fazem N queries
   separadas, e a UX está aceitável.
2. **Service layer começar a duplicar lógica de eager-load** entre
   GraphQL e REST. Sinal de que precisamos de uma camada de
   batching compartilhada.
3. **Adicionar field-level resolvers** a qualquer ObjectType. Se
   precisar acontecer, DataLoader entra junto **na mesma PR**
   para evitar N+1 latente.

## Guard contra regressão

ADR documentado é o guard primário. Adicionalmente:

- Code review checklist deve exigir que qualquer nova
  `graphene.Field(<NestedObjectType>, ...)` com resolver custom
  inclua DataLoader.
- Se algum dia a regressão acontecer e for difícil de pegar via
  review, criar `scripts/check_graphql_field_resolvers.py` que
  detecta `def resolve_<x>(self, info, ...)` em arquivos
  diferentes de `app/graphql/queries/` (resolvers raiz são OK).

## Histórico

- 2026-05-02 — ADR criada após auditoria 2026-05-01 (#1135).
- Issue #1135 fechada como **wontfix**: trabalho não aplicável
  na arquitetura atual.
