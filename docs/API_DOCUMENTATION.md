# API Documentation (As-Is)

Este documento descreve o comportamento real da API com base no código atual da branch.

## Base URL
- Local (Docker): `http://localhost:3333`

## Artefatos de referência GraphQL
- `schema.graphql`: SDL canônico versionado do schema GraphQL.
- `graphql.introspection.json`: introspection estática para docs públicas.
- `graphql.operations.manifest.json`: catálogo curado de queries/mutations, domínio e política de acesso.

Comandos úteis:

```bash
scripts/export_graphql_docs.py --source runtime
scripts/export_graphql_docs.py --source runtime --check
```

Notas:
- `--source runtime` exporta a partir do schema Graphene real.
- `--check` falha quando os artefatos versionados estão desatualizados.
- A documentação pública em `docs.auraxis.com.br/graphql/` deve consumir apenas esses artefatos offline, nunca o endpoint real de produção.

## Autenticação
A API usa JWT via header:

```http
Authorization: Bearer <token>
```

Fluxo atual:
1. `POST /auth/register`
2. `POST /auth/login`
3. `POST /auth/logout`

## Domínios disponíveis
- Autenticação
- Usuário/perfil
- Transações
- Metas
- Carteira (investimentos)

## Nomenclatura oficial de domínio
- `wallet`: domínio de carteira do usuário.
- `investment`: posição/ativo específico dentro da carteira (`investment_id`).
- `investment operation`: evento de compra/venda vinculado a um `investment_id`.
- `ticker`: símbolo de mercado usado para cotação de ativos (ex.: `PETR4`).
- Não existe endpoint REST `/ticker`; operações de ticker ficam no domínio GraphQL e no contexto de carteira.

## Endpoints

## 1) Auth
- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`

### `POST /auth/register`
Cria usuário com `name`, `email`, `password`.

Contrato de resposta:
- Padrão legado (default): sem envelope `success/data/meta`.
- Novo contrato: enviar header `X-API-Contract: v2`.

Resposta de sucesso:
- `201`
- Com `X-API-Contract: v2`, retorna envelope padronizado e usuário em `data.user`.

Erros comuns:
- `409` email já cadastrado
- `400` erro de validação
- Em `v2`, erros retornam `error.code` semântico (`CONFLICT`, `VALIDATION_ERROR`).

### `POST /auth/login`
Aceita `email` ou `name` + `password`.

Contrato de resposta:
- Padrão legado (default): sem envelope `success/data/meta`.
- Novo contrato: enviar header `X-API-Contract: v2`.

Resposta de sucesso:
- `200` com token JWT
- Com `X-API-Contract: v2`, token fica em `data.token` e usuário em `data.user`.

Erros comuns:
- `400` credenciais ausentes
- `401` credenciais inválidas
- Em `v2`, erros retornam `error.code` (`VALIDATION_ERROR`, `UNAUTHORIZED`).

### `POST /auth/logout`
Revoga a sessão atual do usuário autenticado.

Contrato de resposta:
- Padrão legado (default): `{"message": "Logout successful"}`.
- Novo contrato: enviar header `X-API-Contract: v2`.

Resposta de sucesso:
- `200`
- Com `X-API-Contract: v2`, retorna envelope padronizado.

## 2) User
- `GET /user/bootstrap`
- `PUT /user/profile`
- `GET /user/me`
- `GET /user/notification-preferences`
- `PATCH /user/notification-preferences`

Contrato de resposta:
- Padrão legado (default): sem envelope `success/data/meta`.
- Contrato padronizado: enviar header `X-API-Contract: v2`.
- Contrato canônico de contexto autenticado: `X-API-Contract: v3` em `GET /user/me`.

### `GET /user/bootstrap`
Retorna um agregado explícito para bootstrap de home/frontend, sem deformar `/user/me`.

Ownership:
- `GET /user/me` com `v3`: contexto autenticado canônico
- `GET /transactions`: coleção canônica de transações
- `GET /wallet`: coleção canônica de carteira
- `GET /user/bootstrap`: agregado leve para reduzir round-trips iniciais

Resposta:
- `user` com shape canônico
- `transactions_preview` com transações recentes
- `wallet` com itens e total

Query params:
- `transactions_limit` (`1-50`, default `10`)

Observações:
- o bootstrap não aceita filtros de coleção completos;
- para listagens/filtros reais, usar `/transactions` e `/wallet`.

### `PUT /user/profile`
Atualiza perfil financeiro/pessoal do usuário autenticado.

Campos suportados:
- `gender`
- `birth_date`
- `monthly_income`
- `net_worth`
- `monthly_expenses`
- `initial_investment`
- `monthly_investment`
- `investment_goal_date`

Resposta de sucesso:
- `200`
- Com `X-API-Contract: v2`, retorna envelope padronizado e perfil em `data.user`.

Erros comuns:
- `400` validação
- `401` token revogado/ausente
- `404` usuário não encontrado

### `GET /user/notification-preferences`
Lista as preferências de notificação do usuário autenticado.

Requer autenticação (`Authorization: Bearer <JWT>` + `X-API-Contract: v2`).

Resposta de sucesso:
- `200` com `data.preferences` — lista de objetos `{category, enabled, global_opt_out}`
- Retorna lista vazia para usuário sem preferências cadastradas

Categorias válidas: `due_soon`, `wallet`, `goals`, `transactions`, `subscription`.

### `PATCH /user/notification-preferences`
Atualiza (upsert) preferências de notificação do usuário autenticado.

Requer autenticação (`Authorization: Bearer <JWT>` + `X-API-Contract: v2`).

Corpo da requisição:
```json
{
  "preferences": [
    { "category": "due_soon", "enabled": true, "global_opt_out": false }
  ]
}
```

Regras:
- Campo `preferences` é obrigatório e deve ser uma lista.
- Cada item exige `category` (string, em `_VALID_CATEGORIES`) e `enabled` (booleano).
- `global_opt_out` é opcional (padrão `false`).
- Operação é upsert: cria ou sobrescreve a preferência da categoria informada.

Resposta de sucesso:
- `200` com `data.preferences` contendo os itens atualizados

Erros comuns:
- `400` campo `preferences` ausente ou tipo inválido (`VALIDATION_ERROR`)
- `400` categoria inválida (`VALIDATION_ERROR`)
- `401` token ausente/inválido

### `GET /user/me`
Com `X-API-Contract: v3`, retorna apenas contexto autenticado canônico:
- `identity`
- `profile`
- `financial_profile`
- `investor_profile`
- `product_context`

Sem `v3`, mantém o legado:
- dados do usuário
- transações paginadas
- carteira do usuário
- com headers de deprecação:
  - `Deprecation: true`
  - `Sunset: Tue, 30 Jun 2026 23:59:59 GMT`
  - `X-Auraxis-Successor-Contract: v3`
  - `X-Auraxis-Successor-Endpoint: /user/bootstrap`

Query params atuais:
- `page`
- `limit`
- `status`
- `month` (`YYYY-MM`)
- Com `X-API-Contract: v2`, retorna envelope padronizado e paginação em `meta.pagination`.
- Com `X-API-Contract: v3`, paginação e filtros de coleção deixam de ser aceitos.
- A recomendação de migração é:
  - `GET /user/me` com `v3` para contexto autenticado
  - `GET /user/bootstrap` para bootstrap de home/frontend

## 3) Transactions
- `POST /transactions`
- `PATCH /transactions/{transaction_id}`
- `PUT /transactions/{transaction_id}` (compatibilidade transitória)
- `DELETE /transactions/{transaction_id}`
- `PATCH /transactions/restore/{transaction_id}`
- `GET /transactions/deleted`
- `DELETE /transactions/{transaction_id}/force`
- `GET /dashboard/overview?month=YYYY-MM`
- `GET /transactions/summary?month=YYYY-MM`
- `GET /transactions/dashboard?month=YYYY-MM` (compatibilidade transitória)
- `GET /transactions/list`
- `GET /transactions/expenses` (compatibilidade transitória)
- `GET /transactions/due-range`

Contrato de resposta:
- Padrão legado (default): sem envelope `success/data/meta`.
- Novo contrato: enviar header `X-API-Contract: v2`.

### `POST /transactions`
Cria transação única ou parcelada (`is_installment=true`).

Suporta:
- tipo `income|expense`
- status (`paid|pending|cancelled|postponed|overdue`)
- recorrência (`is_recurring`, `start_date`, `end_date`)
- parcelamento com soma exata (diferença de arredondamento ajustada na última parcela)
- política de impacto (`impact_policy`):
  - `full`: reflete em cartões, transações, dashboard e orçamentos
  - `cards_only`: reflete em cartões/fatura, mas é ignorado por dashboard e orçamentos
  - `planned_until_bill`: reservado para planejamento até a fatura
- validações de recorrência:
  - `is_recurring=true` exige `start_date` e `end_date`
  - `due_date` deve estar entre `start_date` e `end_date`
  - `start_date` não pode ser maior que `end_date`
- Com `X-API-Contract: v2`:
  - simples em `data.transaction`
  - parcelada em `data.transactions`

### `PATCH /transactions/{transaction_id}`
Atualiza parcialmente os campos da transação.

Regra específica implementada:
- Se `status=paid`, exige `paid_at`.
- `paid_at` não pode ser no futuro.
- Recorrência mantém consistência de intervalo (`start_date <= end_date`) e de `due_date` dentro do período quando `is_recurring=true`.
- `impact_policy` pode ser atualizado com os mesmos valores aceitos na criação.
- Com `X-API-Contract: v2`, retorna envelope padronizado.

### `PUT /transactions/{transaction_id}`
Compatibilidade transitória para update parcial.
- emite headers de deprecação
- sucessor canônico: `PATCH /transactions/{transaction_id}`

### `DELETE /transactions/{transaction_id}`
Soft delete (`deleted=true`).
- Com `X-API-Contract: v2`, retorna envelope padronizado.

### `PATCH /transactions/restore/{transaction_id}`
Restaura transação soft-deleted.
- Com `X-API-Contract: v2`, retorna envelope padronizado.

### `GET /transactions/deleted`
Lista transações deletadas logicamente do usuário.
- Com `X-API-Contract: v2`, itens em `data.deleted_transactions`.

### `DELETE /transactions/{transaction_id}/force`
Remove definitivamente uma transação já soft-deleted.
- Com `X-API-Contract: v2`, retorna envelope padronizado.

### `GET /transactions/summary?month=YYYY-MM`
Calcula total mensal de receitas e despesas e retorna transações do mês.
- Com `X-API-Contract: v2`, itens em `data.items` e paginação em `meta.pagination`.

### `GET /dashboard/overview?month=YYYY-MM`
Read model canônico do dashboard financeiro do MVP1.

Com `X-API-Contract: v2`:
- mês em `data.month`
- totais em `data.totals`
- contagens em `data.counts`
- categorias em `data.top_categories`

### `GET /transactions/dashboard?month=YYYY-MM`
Retorna um dashboard mensal consolidado com foco em visão executiva:
- totais de receita, despesa e saldo (`income_total`, `expense_total`, `balance`)
- contagens por tipo (`income`, `expense`) e total
- contagens por status (`paid`, `pending`, `cancelled`, `postponed`, `overdue`)
- principais categorias (tags) de receita e despesa por valor agregado

Com `X-API-Contract: v2`:
- mês em `data.month`
- totais em `data.totals`
- contagens em `data.counts`
- categorias em `data.top_categories`
- compatibilidade transitória com headers de deprecação
- sucessor canônico: `GET /dashboard/overview?month=YYYY-MM`

### `GET /transactions/list`
Lista transações ativas do usuário.
- Query params suportados:
  - `page`, `per_page`
  - `type` (`income|expense`)
  - `status` (`paid|pending|cancelled|postponed|overdue`)
  - `start_date`, `end_date` (`YYYY-MM-DD`, aplicados em `due_date`)
  - `tag_id`, `account_id`, `credit_card_id` (UUID)
- Com `X-API-Contract: v2`, itens em `data.transactions` e paginação em `meta.pagination`.

Compatibilidade transitória:
- Esta rota emite headers de deprecação a partir da branch `feat/mvp1-backend-consolidation`:
  - `Deprecation: true`
  - `Sunset: Sat, 31 Dec 2026 23:59:59 GMT`
  - `Link: </transactions>; rel="successor-version"`
  - `X-Auraxis-Successor-Endpoint: /transactions`
- Sucessor canônico: `GET /transactions` (com os mesmos query params de filtragem).

### `GET /transactions/expenses`
Lista despesas por período (`due_date`) com métricas agregadas do período.

Compatibilidade transitória:
- sucessor canônico: `GET /transactions?type=expense&start_date=...&end_date=...`
- a rota responde com headers de deprecação

Regras:
- É obrigatório enviar ao menos um parâmetro: `startDate` ou `finalDate`.
- `startDate` e `finalDate` usam formato `YYYY-MM-DD`.
- Se ambos forem enviados, `startDate` não pode ser maior que `finalDate`.

Query params suportados:
- `startDate`
- `finalDate`
- `page`, `per_page`
- `order_by` (`due_date|created_at|amount|title`)
- `order` (`asc|desc`)

Resposta inclui:
- lista paginada de despesas
- contagem total de transações do período
- contagem de receitas do período
- contagem de despesas do período
- Com `X-API-Contract: v2`:
  - despesas em `data.expenses`
  - contadores em `data.counts`
  - paginação em `meta.pagination`

### `GET /transactions/due-range`
Lista transações de receita e despesa por intervalo de vencimento (`due_date`) com visão unificada.

Regras:
- É obrigatório enviar ao menos um parâmetro: `initialDate` ou `finalDate`.
- `initialDate` e `finalDate` usam formato `YYYY-MM-DD`.
- Se ambos forem enviados, `initialDate` não pode ser maior que `finalDate`.

Query params suportados:
- `initialDate`
- `finalDate`
- `page`, `per_page`
- `order_by` (`overdue_first|due_first|due_date|title|card_name`)

Resposta inclui:
- lista paginada unificada em `data.items`
- contagem total, receitas e despesas em `data.counts`
- paginação em `meta.pagination`

## 4) Wallet
- `POST /wallet`
- `GET /wallet`
- `GET /wallet/{investment_id}/history`
- `POST /wallet/{investment_id}/operations`
- `GET /wallet/{investment_id}/operations`
- `PUT /wallet/{investment_id}/operations/{operation_id}`
- `DELETE /wallet/{investment_id}/operations/{operation_id}`
- `GET /wallet/{investment_id}/operations/summary`
- `GET /wallet/{investment_id}/operations/position`
- `GET /wallet/{investment_id}/operations/invested-amount`
- `GET /wallet/{investment_id}/valuation`
- `GET /wallet/valuation`
- `GET /wallet/valuation/history`
- `PUT /wallet/{investment_id}`
- `DELETE /wallet/{investment_id}`

Contrato de resposta:
- Padrão legado (default): sem envelope `success/data/meta`.
- Novo contrato: enviar header `X-API-Contract: v2`.

### `POST /wallet`
Cria item da carteira.

Regras implementadas:
- Com `ticker`: `quantity` obrigatório e `value` não deve ser enviado.
- Sem `ticker`: `value` obrigatório.
- `asset_class` suportado:
  - mercado: `stock`, `fii`, `etf`, `bdr`, `crypto` (exigem `ticker`);
  - renda fixa: `cdb`, `cdi`, `lci`, `lca`, `tesouro` (exigem `annual_rate`);
  - outros: `fund`, `custom`.
- `estimated_value_on_create_date` é calculado via BRAPI (quando há ticker) ou por `value * quantity`.
- Com header `X-API-Contract: v2`, retorna envelope padronizado.

### `GET /wallet`
Lista carteira paginada (`page`, `per_page`).
- Com `X-API-Contract: v2`, paginação vem em `meta.pagination`.

### `GET /wallet/{investment_id}/history`
Retorna histórico paginado de alterações do investimento.
- Com `X-API-Contract: v2`, itens ficam em `data.items`.

### `POST /wallet/{investment_id}/operations`
Registra operação de investimento no ativo da carteira.
- Campos: `operation_type` (`buy`/`sell`), `quantity`, `unit_price`, `fees` (opcional), `executed_at` (opcional), `notes` (opcional).
- Com `X-API-Contract: v2`, retorno em `data.operation`.

### `GET /wallet/{investment_id}/operations`
Lista operações paginadas de um investimento.
- Query params: `page`, `per_page`.
- Com `X-API-Contract: v2`, operações em `data.items` e paginação em `meta.pagination`.

### `PUT /wallet/{investment_id}/operations/{operation_id}`
Atualiza campos da operação (parcial).
- Mantém mesmas validações de domínio para os campos enviados.

### `DELETE /wallet/{investment_id}/operations/{operation_id}`
Remove operação do investimento.

### `GET /wallet/{investment_id}/operations/summary`
Retorna agregado das operações:
- total de operações
- contagem de compras/vendas
- quantidades (`buy`, `sell`, `net`)
- montantes brutos de compra/venda
- preço médio de compra
- taxas totais

### `GET /wallet/{investment_id}/operations/position`
Retorna posição atual e custo médio do investimento:
- total de operações (buy/sell)
- quantidade total comprada e vendida
- quantidade atual em carteira (`current_quantity`)
- custo total da posição aberta (`current_cost_basis`)
- custo médio da posição aberta (`average_cost`)

### `GET /wallet/{investment_id}/operations/invested-amount`
Retorna o valor investido em uma data específica:
- query param obrigatório: `date` (`YYYY-MM-DD`)
- total de operações do dia
- quantidade de compras e vendas do dia
- valor total de compras (`buy_amount`)
- valor total de vendas (`sell_amount`)
- valor líquido investido no dia (`net_invested_amount`)

### `GET /wallet/{investment_id}/valuation`
Retorna a valorização atual de um investimento:
- classe de ativo (`asset_class`) e taxa anual (`annual_rate`, quando houver)
- quantidade efetiva (priorizando quantidade calculada por operações quando existir)
- preço unitário considerado
- valor investido (`invested_amount`)
- valor atual
- P/L absoluto (`profit_loss_amount`)
- P/L percentual (`profit_loss_percent`)
- origem da cotação/valuation (`brapi_market_price`, `fallback_cost_basis`,
  `fallback_estimated_on_create_date`, `manual_value`,
  `fixed_income_projection`)

### `GET /wallet/valuation`
Retorna a valorização consolidada da carteira:
- lista de investimentos com valuation atual
- resumo agregado (`total_investments`, `with_market_data`,
  `without_market_data`, `total_invested_amount`, `total_current_value`,
  `total_profit_loss`, `total_profit_loss_percent`)

### `GET /wallet/valuation/history`
Retorna evolução diária da carteira por período:
- query params canônicos: `start_date`, `end_date` (`YYYY-MM-DD`)
- aliases legados observáveis: `startDate`, `finalDate`
- sem parâmetros: usa janela padrão dos últimos 30 dias
- resumo agregado:
  - `total_buy_amount`
  - `total_sell_amount`
  - `total_net_invested_amount`
  - `final_cumulative_net_invested`
- série diária:
  - operações totais/compras/vendas por dia
  - `buy_amount`, `sell_amount`
  - `net_invested_amount`
  - `cumulative_net_invested`
  - `total_current_value_estimate`
  - `total_profit_loss_estimate`

### `PATCH /wallet/{investment_id}`
Atualiza item da carteira parcialmente e salva histórico quando `quantity` ou `value` mudam.
- Contrato canônico para update parcial.

### `PUT /wallet/{investment_id}`
Alias legado para atualização parcial da carteira.
- Com `X-API-Contract: v2`, retorna envelope padronizado.
- O método canônico é `PATCH /wallet/{investment_id}`.

### `DELETE /wallet/{investment_id}`
Remove item da carteira.
- Com `X-API-Contract: v2`, retorna envelope padronizado.

## 5) Goals
- `GET /goals`
- `POST /goals`
- `GET /goals/{goal_id}`
- `PATCH /goals/{goal_id}`
- `PUT /goals/{goal_id}` (alias legado)
- `DELETE /goals/{goal_id}`
- `GET /goals/{goal_id}/plan`
- `POST /goals/simulate`

Contrato de resposta:
- Padrão legado (default): sem envelope `success/data/meta`.
- Novo contrato: enviar header `X-API-Contract: v2`.
- Atualização canônica de meta: `PATCH /goals/{goal_id}`.

Objetivo do domínio:
- Gerenciar metas financeiras do usuário.
- Expor plano de atingimento com recomendação acionável.
- Permitir simulação sem persistência (what-if).

## 6) GraphQL
- `POST /graphql`

Queries disponíveis:
- `me`
- `transactions`
- `transactionSummary`
- `transactionDashboard`
- `transactionDueRange`
- `goals`
- `goal`
- `goalPlan`
- `walletEntries`
- `walletHistory`
- `investmentOperations`
- `investmentOperationSummary`
- `investmentPosition`
- `investmentInvestedAmount`
- `investmentValuation`
- `portfolioValuation`
- `portfolioValuationHistory`
- `tickers`
- `budgets` — lista orçamentos ativos com gasto calculado no período (auth)
- `budget` — busca orçamento por `id` (auth)
- `budgetSummary` — totais orçado vs gasto no período atual (auth)
- `billingPlans` — catálogo público de planos de assinatura (**público, sem auth**)
- `mySubscription` — estado atual da assinatura do usuário (auth)
- `notificationPreferences` — preferências de notificação do usuário (auth)

Mutations disponíveis:
- `registerUser`
- `login`
- `logout`
- `updateUserProfile`
- `createTransaction`
- `deleteTransaction`
- `createGoal`
- `updateGoal`
- `deleteGoal`
- `simulateGoalPlan`
- `addWalletEntry`
- `updateWalletEntry`
- `deleteWalletEntry`
- `addInvestmentOperation`
- `updateInvestmentOperation`
- `deleteInvestmentOperation`
- `addTicker`
- `deleteTicker`
- `createBudget` — cria novo orçamento (auth); retorna `budget` criado
- `updateBudget` — atualiza orçamento por `id` (auth); retorna `budget` atualizado
- `deleteBudget` — remove orçamento por `id` (auth); retorna `message`
- `createCheckoutSession` — inicia sessão de checkout para upgrade de plano (auth); recebe `planSlug`, retorna `checkoutUrl`
- `cancelSubscription` — cancela assinatura ativa do usuário (auth)
- `updateNotificationPreferences` — upsert de preferências de notificação (auth); recebe lista `preferences: [PreferenceInput]`

Tipos de entrada:
- `PreferenceInput`: `{ category: String!, enabled: Boolean!, globalOptOut: Boolean }`
- Categorias válidas para `PreferenceInput.category`: `due_soon`, `wallet`, `goals`, `transactions`, `subscription`

Observações:
- operações de ticker estão disponíveis no GraphQL; o controller REST legado de ticker foi removido para evitar superfície não suportada.
- `billingPlans` é a única query GraphQL completamente pública; todas as demais exigem `Authorization: Bearer <JWT>`.
- As stubs de billing (`mySubscription`, `createCheckoutSession`, `cancelSubscription`) retornam dados reais do banco mas dependem da integração Asaas para operar end-to-end (issue #835 — pendente).

Autenticação:
- operações protegidas usam `Authorization: Bearer <JWT>`.
- `registerUser`, `login`, `forgotPassword`, `resetPassword`, `resendConfirmationEmail`, `confirmEmail` e `billingPlans` são públicas.

## 7) Budgets
- `GET /budgets`
- `POST /budgets`
- `GET /budgets/summary`
- `GET /budgets/{budget_id}`
- `PATCH /budgets/{budget_id}`
- `DELETE /budgets/{budget_id}`

Todos os endpoints requerem `Authorization: Bearer <JWT>` + `X-API-Contract: v2`.

### `GET /budgets`
Lista todos os orçamentos ativos do usuário com gasto calculado no período corrente.

Resposta de sucesso:
- `200` com `data.items` — lista de orçamentos serializados com `spent_amount`

### `POST /budgets`
Cria um novo orçamento.

Campos suportados:
- `name` (obrigatório) — nome descritivo do orçamento
- `amount` (obrigatório) — valor-limite do orçamento
- `period` — período de apuração: `monthly` (padrão), `weekly`, `custom`
- `start_date`, `end_date` — obrigatórios quando `period=custom` (`YYYY-MM-DD`)
- `tag_id` — UUID opcional para associar ao orçamento uma tag de transações

Resposta de sucesso:
- `201` com `data.budget`

Erros comuns:
- `400` campos obrigatórios ausentes / `period=custom` sem datas (`VALIDATION_ERROR`)
- `401` token ausente/inválido

### `GET /budgets/summary`
Retorna totais consolidados de orçamento vs gasto no período atual de todos os orçamentos ativos.

Resposta de sucesso:
- `200` com `data.summary` contendo `total_budgeted`, `total_spent`, `remaining`

### `GET /budgets/{budget_id}`
Retorna um orçamento específico com gasto calculado.

Erros comuns:
- `403` orçamento pertence a outro usuário
- `404` orçamento não encontrado

### `PATCH /budgets/{budget_id}`
Atualiza parcialmente um orçamento.

Mesmos campos que `POST /budgets` (todos opcionais na edição).

Resposta de sucesso:
- `200` com `data.budget` atualizado

### `DELETE /budgets/{budget_id}`
Remove um orçamento.

Resposta de sucesso:
- `200` com `data` vazio e `message: "Orçamento removido com sucesso"`

## 8) Subscriptions / Billing
- `GET /subscriptions/plans`
- `GET /subscriptions/me`
- `POST /subscriptions/checkout`
- `POST /subscriptions/cancel`
- `POST /subscriptions/webhook`

### `GET /subscriptions/plans`
Catálogo público de planos de assinatura. **Não requer autenticação.**

Resposta de sucesso:
- `200` com `data.plans` — lista de planos disponíveis com `plan_code`, `billing_cycle`, `price`, `features`

### `GET /subscriptions/me`
Retorna o estado atual da assinatura do usuário autenticado.

Requer autenticação.

Resposta de sucesso:
- `200` com `data.subscription` contendo: `id`, `plan_code`, `offer_code`, `status`, `billing_cycle`, `provider`, `trial_ends_at`, `current_period_start`, `current_period_end`, `canceled_at`

Status possíveis: `free`, `trial`, `active`, `past_due`, `canceled`

### `POST /subscriptions/checkout`
Cria sessão de checkout para upgrade de plano.

Requer autenticação.

Corpo da requisição:
```json
{ "plan_slug": "pro_monthly", "billing_cycle": "monthly" }
```

- `plan_slug` obrigatório — slug canônico do plano (ex: `pro_monthly`, `pro_annual`)
- `billing_cycle` opcional — quando enviado junto com slug simples, é composto automaticamente

Resposta de sucesso:
- `201` com `data.checkout_url`, `data.plan_slug`, `data.plan_code`, `data.billing_cycle`, `data.provider`

Erros comuns:
- `400` `plan_slug` ausente ou inválido (`VALIDATION_ERROR`)
- `502` falha no provider de billing (`UPSTREAM_ERROR`)

### `POST /subscriptions/cancel`
Cancela a assinatura ativa do usuário autenticado.

Requer autenticação.

Resposta de sucesso:
- `200` com `data.subscription` no estado `canceled`

Erros comuns:
- `409` assinatura já está cancelada (`ALREADY_CANCELED`)

### `POST /subscriptions/webhook`
Endpoint receptor de eventos do provider de billing (Asaas). **Não usa JWT.**

Autenticação via HMAC signature (`X-Auraxis-Signature`) ou token Asaas (`asaas-access-token`).

Eventos suportados:
- `subscription.activated` → status `ACTIVE`
- `subscription.canceled` / `SUBSCRIPTION_DELETED` → status `CANCELED`
- `subscription.past_due` / `PAYMENT_OVERDUE` → status `PAST_DUE`
- `PAYMENT_RECEIVED` / `PAYMENT_CONFIRMED` → status `ACTIVE`
- Outros eventos → 200 no-op

Todos os eventos são persistidos na tabela `webhook_events` para auditoria e reprocessamento.

Resposta de sucesso:
- `200` com `data.received: true` e `data.processed: true|false`

Erros comuns:
- `401` assinatura inválida (`UNAUTHORIZED`)
- `400` payload não mapeável para assinatura (`VALIDATION_ERROR`)

> **Nota:** A integração end-to-end com Asaas está pendente (issue #835). Os endpoints estão operacionais com o adapter stub; a lógica real de cobrança requer configuração do `ASAAS_API_KEY` e adapter concreto.

## Contratos e status code
A API ainda não está 100% padronizada em payload de sucesso/erro entre todos os controllers.

Referência de padronização (Fase 0):
- `docs/API_RESPONSE_CONTRACT.md`
- `docs/PHASE0_RESPONSE_ADOPTION_PLAN.md`

## Lacunas e TODOs identificados no código (Fase 0)
1. Geração de recorrência foi implementada em serviço/script e com job agendado no GitHub Actions (`.github/workflows/recurrence-job.yml`), dependente de secrets para conexão no banco.
2. Não há CRUD exposto para `Tag`, `Account` e `CreditCard` (existem model/schema, mas sem controller).
3. Recuperação de senha por link ainda não foi implementada no domínio de autenticação.
4. Evolução de perfil V1 (campos mínimos, auto declaração de investidor e questionário auxiliar) ainda está em backlog.
5. Projeto usa Marshmallow/Webargs em runtime; Pydantic não está implementado no fluxo atual.

## Diretrizes para próximas implementações (senior baseline)
- SOLID e separação clara entre Controller, Service e regras de domínio.
- Controller fino, com regras em serviços puros e testáveis.
- Validação centralizada e consistente de contratos de entrada/saída.
- Padronização de erros e códigos HTTP.
- Cobertura de testes por domínio (unitário + integração).
- Dependências externas (BRAPI) com timeout, retry e fallback.
