# transaction controller

Pacote: `app/controllers/transaction/`

## Responsabilidade
Gerenciar ciclo completo de transações financeiras:
- criação (simples e parcelada)
- atualização
- soft delete e restore
- hard delete
- listagens
- resumo mensal
- dashboard mensal

## Blueprint
- Prefixo: `/transactions`

## Helper

## `serialize_transaction(transaction)`
O que faz:
- Converte entidade `Transaction` em dicionário serializável para resposta HTTP.

## Contrato de resposta
- Header opcional: `X-API-Contract: v2`
- Sem header: mantém payload legado atual.
- Com `v2`: retorna envelope padronizado (`success`, `message`, `data`, `error`, `meta`).
- Helper interno de compatibilidade:
  - `_compat_success(...)`
  - `_compat_error(...)`

## Recursos e comportamento

## `TransactionResource.post`
Endpoint: `POST /transactions`

O que faz:
- Exige JWT válido e não revogado.
- Cria transação simples.
- Quando `is_installment=true`, gera múltiplas transações com `installment_group_id`.
- Aceita `impact_policy` (`full`, `cards_only`, `planned_until_bill`) para decidir se um lançamento de cartão afeta dashboard/orçamentos.
- Parcelamento agora garante soma exata:
  - divide com arredondamento controlado
  - aplica diferença residual na última parcela
- Valida recorrência (`is_recurring=true`):
  - exige `start_date` e `end_date`
  - exige `due_date` dentro do intervalo
  - bloqueia intervalo inválido (`start_date > end_date`)

Resposta:
- `201` (simples ou parcelada)
- `500` em erro de persistência
- Contrato v2:
  - simples: `data.transaction`
  - parcelada: `data.transactions`

## `TransactionResource.put`
Endpoint: `PUT /transactions/{transaction_id}`

O que faz:
- Exige JWT válido e autorização por dono da transação.
- Atualiza campos recebidos no payload.
- Regras implementadas:
  - `status=paid` exige `paid_at`
  - `paid_at` só pode existir com `status=paid`
  - `paid_at` não pode ser futuro
  - se recorrente, mantém coerência de datas (`start_date`, `end_date`, `due_date`)
  - `impact_policy` pode ser alterado mantendo a transação como fonte canônica
- Contrato v2:
  - sucesso em `data.transaction`
  - erros com `error.code` (`VALIDATION_ERROR`, `FORBIDDEN`, `NOT_FOUND`)

## `TransactionResource.delete`
Endpoint: `DELETE /transactions/{transaction_id}`

O que faz:
- Soft delete (`deleted = True`) da transação do usuário.
- Contrato v2:
  - sucesso com envelope padrão e `data` vazio.

## `TransactionResource.patch`
Endpoint: `PATCH /transactions/restore/{transaction_id}`

O que faz:
- Restaura transação soft-deleted (`deleted = False`).
- Contrato v2:
  - sucesso com envelope padrão e `data` vazio.

## `TransactionResource.get_deleted`
Endpoint: `GET /transactions/deleted`

O que faz:
- Lista transações marcadas como deletadas do usuário autenticado.
- Contrato v2:
  - itens em `data.deleted_transactions`
  - total em `meta.total`

## `TransactionResource.get_active`
Endpoint: `GET /transactions/list`

O que faz:
- Retorna transações não deletadas do usuário.
- Aplica filtros reais em nível de banco:
  - `type` (`income|expense`)
  - `status` (`paid|pending|cancelled|postponed|overdue`)
  - `start_date` e `end_date` (intervalo por `due_date`)
  - `tag_id`, `account_id`, `credit_card_id`
- Aplica paginação real:
  - `page` (default `1`)
  - `per_page` (default `10`)
- Ordena por `due_date` desc e `created_at` desc.
- Valida parâmetros inválidos com `400` (`VALIDATION_ERROR` no contrato v2).
- Contrato v2:
  - itens em `data.transactions`
  - paginação em `meta.pagination`

## `TransactionExpensePeriodResource.get`
Endpoint: `GET /transactions/expenses`

O que faz:
- Lista despesas por período com base em `due_date`.
- Regras de entrada:
  - ao menos um parâmetro é obrigatório: `startDate` ou `finalDate`
  - ambos aceitam formato `YYYY-MM-DD`
  - se ambos forem enviados, valida `startDate <= finalDate`
- Paginação:
  - `page` (default `1`)
  - `per_page` (default `10`)
- Ordenação:
  - `order_by`: `due_date|created_at|amount|title` (default `due_date`)
  - `order`: `asc|desc` (default `desc`)
- Métricas retornadas para o período filtrado:
  - `total_transactions`
  - `income_transactions`
  - `expense_transactions`
- Contrato v2:
  - itens em `data.expenses`
  - métricas em `data.counts`
  - paginação em `meta.pagination`

## `TransactionDuePeriodResource.get`
Endpoint: `GET /transactions/due-range`

O que faz:
- Lista receitas e despesas em uma consulta unificada por intervalo de vencimento.
- Regras de entrada:
  - ao menos um parâmetro obrigatório: `initialDate` ou `finalDate`
  - ambos aceitam formato `YYYY-MM-DD`
  - se ambos forem enviados, valida `initialDate <= finalDate`
- Paginação:
  - `page` (default `1`)
  - `per_page` (default `10`)
- Ordenação:
  - `order_by`: `overdue_first|due_first|due_date|title|card_name`
- Métricas retornadas para o período filtrado:
  - `total_transactions`
  - `income_transactions`
  - `expense_transactions`
- Contrato v2:
  - itens em `data.items`
  - métricas em `data.counts`
  - paginação em `meta.pagination`

## `TransactionSummaryResource.get`
Endpoint: `GET /transactions/summary?month=YYYY-MM`

O que faz:
- Busca transações do mês e calcula totais:
  - `income_total`
  - `expense_total`
- Retorna também lista paginada no payload.
- Contrato v2:
  - dados em `data.month`, `data.income_total`, `data.expense_total`, `data.items`
  - paginação em `meta.pagination`

## `TransactionMonthlyDashboardResource.get`
Endpoint: `GET /transactions/dashboard?month=YYYY-MM`

O que faz:
- Calcula visão mensal consolidada de transações do usuário.
- Retorna:
  - totais: `income_total`, `expense_total`, `balance`
  - contagens: total, por tipo e por status
  - categorias principais (tags) por valor agregado para:
    - despesas
    - receitas
- Aceita `month` no formato `YYYY-MM` (obrigatório).
- É rota de compatibilidade transitória.
- Sucessor canônico: `GET /dashboard/overview?month=YYYY-MM`.

Contrato:
- Legado:
  - campos no payload raiz (`income_total`, `expense_total`, `balance`, `counts`)
  - listas em `top_expense_categories` e `top_income_categories`
- v2:
  - `data.month`
  - `data.totals`
  - `data.counts`
  - `data.top_categories`

## `TransactionForceDeleteResource.delete`
Endpoint: `DELETE /transactions/{transaction_id}/force`

O que faz:
- Remove permanentemente transação que já esteja soft-deleted.
- Contrato v2:
  - sucesso com envelope padrão e `data` vazio.

## Dependências principais
- `app.models.transaction.Transaction`
- `TransactionType`, `TransactionStatus`
- `TransactionSchema`
- `PaginatedResponse`
- `TransactionAnalyticsService` (agregações de resumo/dashboard)
- `TransactionQueryService` (boundary compartilhado de leitura REST/GraphQL)
- JWT callbacks de revogação

## Pontos incompletos / TODOs (identificados no código)
1. Agendamento automático de recorrência foi configurado via GitHub Actions (`.github/workflows/recurrence-job.yml`), dependendo de secrets de ambiente para conexão no banco.

## Recomendação de implementação futura (sem alterar comportamento agora)
- Extrair casos de uso para `TransactionService` com comandos explícitos (create/update/delete/restore/summary).
- Implementar recorrência com job idempotente (diário/mensal) e testes de não-duplicidade.
