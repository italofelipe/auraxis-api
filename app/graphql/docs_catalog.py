from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GraphQLOperationType = Literal["query", "mutation"]
GraphQLOperationAccess = Literal["public", "auth_required"]
GraphQLDomain = Literal[
    "accounts",
    "ai_advisory",
    "auth",
    "billing",
    "credit_card",
    "dashboard",
    "fiscal",
    "goals",
    "investments",
    "notifications",
    "simulations",
    "tags",
    "transactions",
    "user",
    "wallet",
]

QUERY_AI_INSIGHT_MODULE = "app.graphql.queries.ai_insight"
QUERY_FISCAL_MODULE = "app.graphql.queries.fiscal"
MUTATION_FISCAL_MODULE = "app.graphql.mutations.fiscal"
QUERY_USER_MODULE = "app.graphql.queries.user"
QUERY_DASHBOARD_MODULE = "app.graphql.queries.dashboard"
QUERY_TRANSACTION_MODULE = "app.graphql.queries.transaction"
QUERY_GOAL_MODULE = "app.graphql.queries.goal"
QUERY_SIMULATION_MODULE = "app.graphql.queries.simulation"
QUERY_WALLET_MODULE = "app.graphql.queries.wallet"
QUERY_INVESTMENT_MODULE = "app.graphql.queries.investment"
MUTATION_AUTH_MODULE = "app.graphql.mutations.auth"
MUTATION_TRANSACTION_MODULE = "app.graphql.mutations.transaction"
MUTATION_GOAL_MODULE = "app.graphql.mutations.goal"
MUTATION_SIMULATION_MODULE = "app.graphql.mutations.simulation"
MUTATION_WALLET_MODULE = "app.graphql.mutations.wallet"
MUTATION_INVESTMENT_MODULE = "app.graphql.mutations.investment_operation"
MUTATION_TICKER_MODULE = "app.graphql.mutations.ticker"
QUERY_BUDGET_MODULE = "app.graphql.queries.budget"
QUERY_SUBSCRIPTION_MODULE = "app.graphql.queries.subscription"
QUERY_NOTIFICATION_MODULE = "app.graphql.queries.notification"
MUTATION_BUDGET_MODULE = "app.graphql.mutations.budget"
MUTATION_SUBSCRIPTION_MODULE = "app.graphql.mutations.subscription"
MUTATION_NOTIFICATION_MODULE = "app.graphql.mutations.notification"
QUERY_TAG_MODULE = "app.graphql.queries.tag"
QUERY_ACCOUNT_MODULE = "app.graphql.queries.account"
QUERY_CREDIT_CARD_MODULE = "app.graphql.queries.credit_card"
MUTATION_TAG_MODULE = "app.graphql.mutations.tag"
MUTATION_ACCOUNT_MODULE = "app.graphql.mutations.account"
MUTATION_BANK_STATEMENT_MODULE = "app.graphql.mutations.bank_statement"
ADVANCED_SIMULATIONS = "advanced_simulations"


@dataclass(frozen=True)
class GraphQLOperationDoc:
    name: str
    operation_type: GraphQLOperationType
    domain: GraphQLDomain
    access: GraphQLOperationAccess
    summary: str
    source_module: str
    legacy_alias_of: str | None = None
    entitlements: tuple[str, ...] = ()

    def to_manifest_entry(self) -> dict[str, object]:
        entry: dict[str, object] = {
            "name": self.name,
            "operation_type": self.operation_type,
            "domain": self.domain,
            "access": self.access,
            "summary": self.summary,
            "source_module": self.source_module,
        }
        if self.legacy_alias_of:
            entry["legacy_alias_of"] = self.legacy_alias_of
        if self.entitlements:
            entry["entitlements"] = list(self.entitlements)
        return entry


GRAPHQL_OPERATION_CATALOG: tuple[GraphQLOperationDoc, ...] = (
    GraphQLOperationDoc(
        name="me",
        operation_type="query",
        domain="user",
        access="auth_required",
        summary="Retorna o perfil do usuário autenticado.",
        source_module=QUERY_USER_MODULE,
    ),
    GraphQLOperationDoc(
        name="dashboardOverview",
        operation_type="query",
        domain="dashboard",
        access="auth_required",
        summary="Retorna o read model canônico do dashboard financeiro mensal.",
        source_module=QUERY_DASHBOARD_MODULE,
    ),
    GraphQLOperationDoc(
        name="weeklySummary",
        operation_type="query",
        domain="dashboard",
        access="auth_required",
        summary=(
            "Resumo semanal: comparativo semana atual vs anterior + "
            "série temporal para gráfico (B13)."
        ),
        source_module=QUERY_DASHBOARD_MODULE,
    ),
    GraphQLOperationDoc(
        name="transactions",
        operation_type="query",
        domain="transactions",
        access="auth_required",
        summary="Lista transações ativas do usuário com paginação e filtros.",
        source_module=QUERY_TRANSACTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="transaction",
        operation_type="query",
        domain="transactions",
        access="auth_required",
        summary="Retorna uma transação específica do usuário.",
        source_module=QUERY_TRANSACTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="transactionSummary",
        operation_type="query",
        domain="transactions",
        access="auth_required",
        summary="Retorna resumo mensal de transações com itens paginados.",
        source_module=QUERY_TRANSACTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="transactionDashboard",
        operation_type="query",
        domain="dashboard",
        access="auth_required",
        summary="Alias legado do dashboard mensal; prefira dashboardOverview.",
        source_module=QUERY_DASHBOARD_MODULE,
        legacy_alias_of="dashboardOverview",
    ),
    GraphQLOperationDoc(
        name="transactionDueRange",
        operation_type="query",
        domain="transactions",
        access="auth_required",
        summary="Lista transações por faixa de vencimento com métricas agregadas.",
        source_module=QUERY_TRANSACTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="goals",
        operation_type="query",
        domain="goals",
        access="auth_required",
        summary="Lista metas do usuário com paginação e filtro de status.",
        source_module=QUERY_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="goal",
        operation_type="query",
        domain="goals",
        access="auth_required",
        summary="Retorna uma meta específica do usuário.",
        source_module=QUERY_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="goalPlan",
        operation_type="query",
        domain="goals",
        access="auth_required",
        summary="Retorna o plano projetado de uma meta existente.",
        source_module=QUERY_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="goalContributions",
        operation_type="query",
        domain="goals",
        access="auth_required",
        summary=(
            "Lista o histórico paginado de contribuições (aportes/retiradas) "
            "de uma meta. Paridade com GET /goals/{id}/contributions."
        ),
        source_module=QUERY_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="installmentVsCashCalculate",
        operation_type="query",
        domain="simulations",
        access="public",
        summary="Calcula a comparação entre pagamento parcelado e à vista.",
        source_module=QUERY_SIMULATION_MODULE,
    ),
    GraphQLOperationDoc(
        name="simulations",
        operation_type="query",
        domain="simulations",
        access="auth_required",
        summary=(
            "Lista as simulações persistidas do usuário autenticado, "
            "com paginação e filtro opcional por toolId."
        ),
        source_module=QUERY_SIMULATION_MODULE,
    ),
    GraphQLOperationDoc(
        name="simulation",
        operation_type="query",
        domain="simulations",
        access="auth_required",
        summary="Retorna o detalhe de uma simulação persistida do usuário.",
        source_module=QUERY_SIMULATION_MODULE,
    ),
    GraphQLOperationDoc(
        name="simulationQuota",
        operation_type="query",
        domain="simulations",
        access="auth_required",
        summary="Snapshot da quota freemium de simulações do usuário (#1409).",
        source_module=QUERY_SIMULATION_MODULE,
    ),
    GraphQLOperationDoc(
        name="walletEntries",
        operation_type="query",
        domain="wallet",
        access="auth_required",
        summary="Lista entradas da carteira do usuário.",
        source_module=QUERY_WALLET_MODULE,
    ),
    GraphQLOperationDoc(
        name="walletHistory",
        operation_type="query",
        domain="wallet",
        access="auth_required",
        summary="Retorna histórico paginado de um investimento da carteira.",
        source_module=QUERY_WALLET_MODULE,
    ),
    GraphQLOperationDoc(
        name="tickers",
        operation_type="query",
        domain="wallet",
        access="auth_required",
        summary="Lista os tickers cadastrados pelo usuário.",
        source_module=QUERY_WALLET_MODULE,
    ),
    GraphQLOperationDoc(
        name="investmentOperations",
        operation_type="query",
        domain="investments",
        access="auth_required",
        summary="Lista operações de um investimento com paginação.",
        source_module=QUERY_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="investmentOperationSummary",
        operation_type="query",
        domain="investments",
        access="auth_required",
        summary="Retorna o resumo agregado das operações de um investimento.",
        source_module=QUERY_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="investmentPosition",
        operation_type="query",
        domain="investments",
        access="auth_required",
        summary="Retorna a posição consolidada de um investimento.",
        source_module=QUERY_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="investmentInvestedAmount",
        operation_type="query",
        domain="investments",
        access="auth_required",
        summary="Calcula o valor investido acumulado em uma data específica.",
        source_module=QUERY_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="investmentValuation",
        operation_type="query",
        domain="investments",
        access="auth_required",
        summary="Retorna a valorização atual de um investimento específico.",
        source_module=QUERY_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="portfolioValuation",
        operation_type="query",
        domain="investments",
        access="auth_required",
        summary="Retorna a valorização consolidada do portfólio do usuário.",
        source_module=QUERY_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="portfolioValuationHistory",
        operation_type="query",
        domain="investments",
        access="auth_required",
        summary="Retorna o histórico de valorização do portfólio em um período.",
        source_module=QUERY_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="registerUser",
        operation_type="mutation",
        domain="auth",
        access="public",
        summary="Registra um novo usuário na plataforma.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="login",
        operation_type="mutation",
        domain="auth",
        access="public",
        summary="Autentica um usuário por email e retorna token JWT.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="logout",
        operation_type="mutation",
        domain="auth",
        access="auth_required",
        summary="Revoga a sessão atual do usuário autenticado.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="forgotPassword",
        operation_type="mutation",
        domain="auth",
        access="public",
        summary="Solicita o fluxo de redefinição de senha.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="resetPassword",
        operation_type="mutation",
        domain="auth",
        access="public",
        summary="Conclui a redefinição de senha com token válido.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="resendConfirmationEmail",
        operation_type="mutation",
        domain="auth",
        access="public",
        summary="Reenvia o email de confirmação com resposta neutra.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="confirmEmail",
        operation_type="mutation",
        domain="auth",
        access="public",
        summary="Confirma a conta do usuário a partir de um token válido.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateUserProfile",
        operation_type="mutation",
        domain="user",
        access="auth_required",
        summary="Atualiza o perfil financeiro e pessoal do usuário.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="createTransaction",
        operation_type="mutation",
        domain="transactions",
        access="auth_required",
        summary="Cria uma transação única, recorrente ou parcelada.",
        source_module=MUTATION_TRANSACTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="deleteTransaction",
        operation_type="mutation",
        domain="transactions",
        access="auth_required",
        summary="Realiza soft delete de uma transação do usuário.",
        source_module=MUTATION_TRANSACTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateTransaction",
        operation_type="mutation",
        domain="transactions",
        access="auth_required",
        summary="Atualiza parcialmente uma transação do usuário.",
        source_module=MUTATION_TRANSACTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="createGoal",
        operation_type="mutation",
        domain="goals",
        access="auth_required",
        summary="Cria uma meta financeira.",
        source_module=MUTATION_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateGoal",
        operation_type="mutation",
        domain="goals",
        access="auth_required",
        summary="Atualiza uma meta existente.",
        source_module=MUTATION_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="deleteGoal",
        operation_type="mutation",
        domain="goals",
        access="auth_required",
        summary="Remove uma meta existente.",
        source_module=MUTATION_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="simulateGoalPlan",
        operation_type="mutation",
        domain="goals",
        access="auth_required",
        summary="Simula o plano de aporte de uma meta sem persistir dados.",
        source_module=MUTATION_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="recordGoalContribution",
        operation_type="mutation",
        domain="goals",
        access="auth_required",
        summary=(
            "Registra um aporte (+) ou retirada (-) em uma meta, atualizando o "
            "valor acumulado. Paridade com POST /goals/{id}/contributions."
        ),
        source_module=MUTATION_GOAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="saveInstallmentVsCashSimulation",
        operation_type="mutation",
        domain="simulations",
        access="auth_required",
        summary="Salva uma simulação de parcelado vs à vista no histórico do usuário.",
        source_module=MUTATION_SIMULATION_MODULE,
    ),
    GraphQLOperationDoc(
        name="createGoalFromInstallmentVsCashSimulation",
        operation_type="mutation",
        domain="simulations",
        access="auth_required",
        summary="Converte uma simulação em meta financeira.",
        source_module=MUTATION_SIMULATION_MODULE,
        entitlements=(ADVANCED_SIMULATIONS,),
    ),
    GraphQLOperationDoc(
        name="createPlannedExpenseFromInstallmentVsCashSimulation",
        operation_type="mutation",
        domain="simulations",
        access="auth_required",
        summary="Converte uma simulação em despesa planejada.",
        source_module=MUTATION_SIMULATION_MODULE,
        entitlements=(ADVANCED_SIMULATIONS,),
    ),
    GraphQLOperationDoc(
        name="consumeSimulationQuota",
        operation_type="mutation",
        domain="simulations",
        access="auth_required",
        summary="Consome 1 simulação da quota freemium do usuário (#1409).",
        source_module=MUTATION_SIMULATION_MODULE,
    ),
    GraphQLOperationDoc(
        name="addWalletEntry",
        operation_type="mutation",
        domain="wallet",
        access="auth_required",
        summary="Adiciona um item à carteira do usuário.",
        source_module=MUTATION_WALLET_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateWalletEntry",
        operation_type="mutation",
        domain="wallet",
        access="auth_required",
        summary="Atualiza um item da carteira do usuário.",
        source_module=MUTATION_WALLET_MODULE,
    ),
    GraphQLOperationDoc(
        name="deleteWalletEntry",
        operation_type="mutation",
        domain="wallet",
        access="auth_required",
        summary="Remove um item da carteira do usuário.",
        source_module=MUTATION_WALLET_MODULE,
    ),
    GraphQLOperationDoc(
        name="addInvestmentOperation",
        operation_type="mutation",
        domain="investments",
        access="auth_required",
        summary="Registra uma operação em um investimento existente.",
        source_module=MUTATION_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateInvestmentOperation",
        operation_type="mutation",
        domain="investments",
        access="auth_required",
        summary="Atualiza uma operação de investimento existente.",
        source_module=MUTATION_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="deleteInvestmentOperation",
        operation_type="mutation",
        domain="investments",
        access="auth_required",
        summary="Remove uma operação de investimento existente.",
        source_module=MUTATION_INVESTMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="addTicker",
        operation_type="mutation",
        domain="wallet",
        access="auth_required",
        summary="Adiciona um ticker ao acompanhamento do usuário.",
        source_module=MUTATION_TICKER_MODULE,
    ),
    GraphQLOperationDoc(
        name="deleteTicker",
        operation_type="mutation",
        domain="wallet",
        access="auth_required",
        summary="Remove um ticker do acompanhamento do usuário.",
        source_module=MUTATION_TICKER_MODULE,
    ),
    # Budget queries
    GraphQLOperationDoc(
        name="budgets",
        operation_type="query",
        domain="billing",
        access="auth_required",
        summary="Lista os orçamentos ativos do usuário com métricas de gasto.",
        source_module=QUERY_BUDGET_MODULE,
    ),
    GraphQLOperationDoc(
        name="budget",
        operation_type="query",
        domain="billing",
        access="auth_required",
        summary="Retorna um orçamento específico do usuário.",
        source_module=QUERY_BUDGET_MODULE,
    ),
    GraphQLOperationDoc(
        name="budgetSummary",
        operation_type="query",
        domain="billing",
        access="auth_required",
        summary="Retorna o resumo consolidado dos orçamentos do usuário.",
        source_module=QUERY_BUDGET_MODULE,
    ),
    # Budget mutations
    GraphQLOperationDoc(
        name="createBudget",
        operation_type="mutation",
        domain="billing",
        access="auth_required",
        summary="Cria um novo orçamento para o usuário.",
        source_module=MUTATION_BUDGET_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateBudget",
        operation_type="mutation",
        domain="billing",
        access="auth_required",
        summary="Atualiza um orçamento existente do usuário.",
        source_module=MUTATION_BUDGET_MODULE,
    ),
    GraphQLOperationDoc(
        name="deleteBudget",
        operation_type="mutation",
        domain="billing",
        access="auth_required",
        summary="Remove um orçamento do usuário.",
        source_module=MUTATION_BUDGET_MODULE,
    ),
    # Subscription/billing queries
    GraphQLOperationDoc(
        name="billingPlans",
        operation_type="query",
        domain="billing",
        access="public",
        summary="Retorna o catálogo público de planos de assinatura.",
        source_module=QUERY_SUBSCRIPTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="mySubscription",
        operation_type="query",
        domain="billing",
        access="auth_required",
        summary="Retorna o estado atual da assinatura do usuário autenticado.",
        source_module=QUERY_SUBSCRIPTION_MODULE,
    ),
    # Subscription mutations
    GraphQLOperationDoc(
        name="createCheckoutSession",
        operation_type="mutation",
        domain="billing",
        access="auth_required",
        summary="Cria uma sessão de checkout para assinatura de um plano.",
        source_module=MUTATION_SUBSCRIPTION_MODULE,
    ),
    GraphQLOperationDoc(
        name="cancelSubscription",
        operation_type="mutation",
        domain="billing",
        access="auth_required",
        summary="Cancela a assinatura ativa do usuário autenticado.",
        source_module=MUTATION_SUBSCRIPTION_MODULE,
    ),
    # Notification preferences
    GraphQLOperationDoc(
        name="notificationPreferences",
        operation_type="query",
        domain="notifications",
        access="auth_required",
        summary="Retorna as preferências de notificação do usuário autenticado.",
        source_module=QUERY_NOTIFICATION_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateNotificationPreferences",
        operation_type="mutation",
        domain="notifications",
        access="auth_required",
        summary="Atualiza as preferências de notificação do usuário autenticado.",
        source_module=MUTATION_NOTIFICATION_MODULE,
    ),
    # Multi-device sessions (#1028)
    GraphQLOperationDoc(
        name="revokeSession",
        operation_type="mutation",
        domain="auth",
        access="auth_required",
        summary="Revoga uma sessão específica pelo ID (multi-device).",
        source_module=MUTATION_AUTH_MODULE,
    ),
    GraphQLOperationDoc(
        name="revokeAllSessions",
        operation_type="mutation",
        domain="auth",
        access="auth_required",
        summary="Revoga todas as sessões ativas — logout global.",
        source_module=MUTATION_AUTH_MODULE,
    ),
    # Tags (#1148)
    GraphQLOperationDoc(
        name="tags",
        operation_type="query",
        domain="tags",
        access="auth_required",
        summary="Lista todas as tags do usuário autenticado.",
        source_module=QUERY_TAG_MODULE,
    ),
    GraphQLOperationDoc(
        name="tag",
        operation_type="query",
        domain="tags",
        access="auth_required",
        summary="Retorna uma tag pelo ID.",
        source_module=QUERY_TAG_MODULE,
    ),
    GraphQLOperationDoc(
        name="createTag",
        operation_type="mutation",
        domain="tags",
        access="auth_required",
        summary="Cria uma nova tag para o usuário.",
        source_module=MUTATION_TAG_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateTag",
        operation_type="mutation",
        domain="tags",
        access="auth_required",
        summary="Atualiza nome, cor ou ícone de uma tag existente.",
        source_module=MUTATION_TAG_MODULE,
    ),
    GraphQLOperationDoc(
        name="deleteTag",
        operation_type="mutation",
        domain="tags",
        access="auth_required",
        summary="Remove uma tag do usuário.",
        source_module=MUTATION_TAG_MODULE,
    ),
    # Accounts (#1148)
    GraphQLOperationDoc(
        name="accounts",
        operation_type="query",
        domain="accounts",
        access="auth_required",
        summary="Lista todas as contas bancárias do usuário autenticado.",
        source_module=QUERY_ACCOUNT_MODULE,
    ),
    GraphQLOperationDoc(
        name="account",
        operation_type="query",
        domain="accounts",
        access="auth_required",
        summary="Retorna uma conta bancária pelo ID.",
        source_module=QUERY_ACCOUNT_MODULE,
    ),
    GraphQLOperationDoc(
        name="createAccount",
        operation_type="mutation",
        domain="accounts",
        access="auth_required",
        summary="Cria uma nova conta bancária para o usuário.",
        source_module=MUTATION_ACCOUNT_MODULE,
    ),
    GraphQLOperationDoc(
        name="updateAccount",
        operation_type="mutation",
        domain="accounts",
        access="auth_required",
        summary="Atualiza dados de uma conta bancária existente.",
        source_module=MUTATION_ACCOUNT_MODULE,
    ),
    GraphQLOperationDoc(
        name="deleteAccount",
        operation_type="mutation",
        domain="accounts",
        access="auth_required",
        summary="Remove uma conta bancária do usuário.",
        source_module=MUTATION_ACCOUNT_MODULE,
    ),
    # Credit Cards (MVP-3 / #1284-#1286)
    GraphQLOperationDoc(
        name="creditCards",
        operation_type="query",
        domain="credit_card",
        access="auth_required",
        summary="Lista todos os cartões de crédito do usuário autenticado.",
        source_module=QUERY_CREDIT_CARD_MODULE,
    ),
    GraphQLOperationDoc(
        name="creditCardBill",
        operation_type="query",
        domain="credit_card",
        access="auth_required",
        summary=(
            "Retorna a fatura (ciclo + transações + totais) de um cartão para "
            "o mês solicitado (YYYY-MM)."
        ),
        source_module=QUERY_CREDIT_CARD_MODULE,
    ),
    GraphQLOperationDoc(
        name="creditCardUtilization",
        operation_type="query",
        domain="credit_card",
        access="auth_required",
        summary=(
            "Retorna o snapshot de utilização do ciclo aberto: committed, "
            "available, limit e utilization_pct."
        ),
        source_module=QUERY_CREDIT_CARD_MODULE,
    ),
    # Bank Statement Import (#1148)
    GraphQLOperationDoc(
        name="previewBankStatement",
        operation_type="mutation",
        domain="transactions",
        access="auth_required",
        summary=(
            "Faz o parse de um extrato bancário (CSV ou OFX) e retorna preview "
            "com detecção de duplicatas. Nenhum dado é gravado."
        ),
        source_module=MUTATION_BANK_STATEMENT_MODULE,
    ),
    GraphQLOperationDoc(
        name="confirmBankImport",
        operation_type="mutation",
        domain="transactions",
        access="auth_required",
        summary=(
            "Persiste as entradas selecionadas do extrato bancário como transações. "
            "Suporta modos 'selective' e 'replace_month'."
        ),
        source_module=MUTATION_BANK_STATEMENT_MODULE,
    ),
    # Fiscal domain (#1247)
    GraphQLOperationDoc(
        name="receivables",
        operation_type="query",
        domain="fiscal",
        access="auth_required",
        summary=(
            "Lista recebíveis do usuário. Filtro opcional por status: "
            "pending | received | cancelled. Valores estimativos — exibir disclaimer."
        ),
        source_module=QUERY_FISCAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="receivablesSummary",
        operation_type="query",
        domain="fiscal",
        access="auth_required",
        summary=(
            "Retorna totais agregados de receitas esperadas, recebidas e pendentes. "
            "Valores são estimativos — exibir o campo 'disclaimer' ao usuário."
        ),
        source_module=QUERY_FISCAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="fiscalDocuments",
        operation_type="query",
        domain="fiscal",
        access="auth_required",
        summary=(
            "Lista documentos fiscais do usuário. Filtro opcional por tipo: "
            "service_invoice | product_invoice | receipt | debit_note | credit_note."
        ),
        source_module=QUERY_FISCAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="createReceivable",
        operation_type="mutation",
        domain="fiscal",
        access="auth_required",
        summary=(
            "Cria um recebível manual. "
            "Deprecated: preferir POST /fiscal/receivables (ADR-0002)."
        ),
        source_module=MUTATION_FISCAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="markReceivableReceived",
        operation_type="mutation",
        domain="fiscal",
        access="auth_required",
        summary=(
            "Marca um recebível como recebido com data e valor. "
            "Deprecated: preferir PATCH /fiscal/receivables/{id}/receive (ADR-0002)."
        ),
        source_module=MUTATION_FISCAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="cancelReceivable",
        operation_type="mutation",
        domain="fiscal",
        access="auth_required",
        summary=(
            "Cancela um recebível pendente. "
            "Deprecated: preferir DELETE /fiscal/receivables/{id} (ADR-0002)."
        ),
        source_module=MUTATION_FISCAL_MODULE,
    ),
    GraphQLOperationDoc(
        name="createFiscalDocument",
        operation_type="mutation",
        domain="fiscal",
        access="auth_required",
        summary=(
            "Cria um documento fiscal. "
            "Deprecated: preferir POST /fiscal/fiscal-documents (ADR-0002)."
        ),
        source_module=MUTATION_FISCAL_MODULE,
    ),
    # AI Advisory (#1231)
    GraphQLOperationDoc(
        name="aiInsightHistory",
        operation_type="query",
        domain="ai_advisory",
        access="auth_required",
        summary=(
            "Retorna o histórico paginado de insights gerados por IA para o usuário "
            "autenticado, ordenado do mais recente ao mais antigo."
        ),
        source_module=QUERY_AI_INSIGHT_MODULE,
    ),
    # AI Advisory — change detection sem LLM (#1482)
    GraphQLOperationDoc(
        name="aiInsightChangeStatus",
        operation_type="query",
        domain="ai_advisory",
        access="auth_required",
        summary=(
            "Indica se o snapshot financeiro mudou desde o último insight do "
            "período (compara context_hash) SEM chamar o LLM — sem custo de tokens "
            "e sem consumir cota. Usado para confirmar 'nada mudou, gerar mesmo "
            "assim?'. Paridade com GET /ai/insights/change-status."
        ),
        source_module=QUERY_AI_INSIGHT_MODULE,
    ),
    # AI Advisory — cached Radar de Gastos (#1455)
    GraphQLOperationDoc(
        name="spendingPatternsLatest",
        operation_type="query",
        domain="ai_advisory",
        access="auth_required",
        summary=(
            "Retorna o último radar de gastos compulsivos já gerado pelo cron "
            "diário (somente leitura, sem consumir cota de IA). 'patternsJson' "
            "traz os padrões serializados; 'generatedAt' é null quando ainda não "
            "há análise. Paridade com GET /ai/insights/spending-patterns/latest."
        ),
        source_module=QUERY_AI_INSIGHT_MODULE,
    ),
    # AI Advisory — generate (MVP-3 / #1287 #1288)
    GraphQLOperationDoc(
        name="generateAiInsight",
        operation_type="mutation",
        domain="ai_advisory",
        access="auth_required",
        summary=(
            "Gera um insight financeiro period-aware (daily/weekly/monthly) com "
            "itens marcados por dimension (general | transactions | credit_cards |"
            " goals | budgets). Paridade com POST /ai/insights/generate."
        ),
        source_module="app.graphql.mutations.ai_insight",
    ),
    # AI Advisory — feedback (#1387)
    GraphQLOperationDoc(
        name="submitAiInsightFeedback",
        operation_type="mutation",
        domain="ai_advisory",
        access="auth_required",
        summary=(
            "Registra feedback (notas 0–5 de relevância/veracidade/profundidade/"
            "utilidade + comentário) de um insight do próprio usuário. Paridade "
            "com POST /ai/insights/<id>/feedback."
        ),
        source_module="app.graphql.mutations.ai_insight",
    ),
    # Onboarding completion (#1471)
    GraphQLOperationDoc(
        name="completeOnboarding",
        operation_type="mutation",
        domain="user",
        access="auth_required",
        summary=(
            "Marca o onboarding do usuário autenticado como concluído "
            "(idempotente). Paridade com POST /user/onboarding/complete."
        ),
        source_module="app.graphql.mutations.user",
    ),
)


def get_graphql_operation_catalog() -> tuple[GraphQLOperationDoc, ...]:
    return GRAPHQL_OPERATION_CATALOG


def get_graphql_operation_names(
    operation_type: GraphQLOperationType,
) -> set[str]:
    return {
        operation.name
        for operation in GRAPHQL_OPERATION_CATALOG
        if operation.operation_type == operation_type
    }


def build_graphql_operations_manifest() -> list[dict[str, object]]:
    return [operation.to_manifest_entry() for operation in GRAPHQL_OPERATION_CATALOG]
