from __future__ import annotations

import graphene

from app.graphql.scalars import DecimalScalar


class UserType(graphene.ObjectType):
    id = graphene.ID(required=True)
    name = graphene.String(required=True)
    email = graphene.String(required=True)
    gender = graphene.String()
    birth_date = graphene.String()
    monthly_income = DecimalScalar()
    monthly_income_net = DecimalScalar()
    net_worth = DecimalScalar()
    monthly_expenses = DecimalScalar()
    initial_investment = DecimalScalar()
    monthly_investment = DecimalScalar()
    investment_goal_date = graphene.String()
    state_uf = graphene.String()
    occupation = graphene.String()
    investor_profile = graphene.String()
    financial_objectives = graphene.String()
    # B11: quiz-derived suggestion fields
    investor_profile_suggested = graphene.String()
    profile_quiz_score = graphene.Int()
    taxonomy_version = graphene.String()
    avatar_url = graphene.String()
    # #1471: server-side onboarding completion marker (ISO 8601 or null)
    onboarding_completed_at = graphene.String()
    # #1325 / #1331: 14-day email verification grace period
    email_verified = graphene.Boolean()
    email_verification_deadline_at = graphene.String()
    email_verification_required_now = graphene.Boolean()
    days_until_email_required = graphene.Int()


class AuthPayloadType(graphene.ObjectType):
    token = graphene.String()
    user = graphene.Field(UserType)
    message = graphene.String(required=True)


class TransactionTypeObject(graphene.ObjectType):
    id = graphene.ID(required=True)
    title = graphene.String(required=True)
    amount = graphene.String(required=True)
    type = graphene.String(required=True)
    due_date = graphene.String(required=True)
    start_date = graphene.String()
    end_date = graphene.String()
    description = graphene.String()
    observation = graphene.String()
    is_recurring = graphene.Boolean(required=True)
    is_installment = graphene.Boolean(required=True)
    installment_count = graphene.Int()
    recurrence_interval = graphene.Int()
    recurrence_unit = graphene.String()
    category = graphene.String()
    tag_id = graphene.String()
    account_id = graphene.String()
    credit_card_id = graphene.String()
    status = graphene.String(required=True)
    currency = graphene.String(required=True)
    source = graphene.String(required=True)
    external_id = graphene.String()
    bank_name = graphene.String()
    installment_group_id = graphene.String()
    paid_at = graphene.String()
    created_at = graphene.String()
    updated_at = graphene.String()


class PaginationType(graphene.ObjectType):
    total = graphene.Int(required=True)
    page = graphene.Int(required=True)
    per_page = graphene.Int(required=True)
    pages = graphene.Int()


# ---------------------------------------------------------------------------
# Canonical mutation output types (#1149)
# ---------------------------------------------------------------------------
# All new mutations MUST use one of these shapes.  Existing deprecated CRUD
# mutations retain their per-entity field layout during the deprecation window
# (see ADR-0002 / ADR-0004).  Migration tracking: #1149.


class ValidationError(graphene.ObjectType):
    """A single field-level validation failure inside a mutation payload."""

    field = graphene.String(
        description="The input field that failed validation, or null for "
        "document-level errors.",
    )
    message = graphene.String(
        required=True,
        description="Human-readable description of the failure.",
    )


class MutationPayload(graphene.ObjectType):
    """Base shape for new mutations: ok + message + errors.

    Concrete mutations subclass this and add a typed ``data`` field::

        class AddTickerPayload(MutationPayload):
            data = graphene.Field(TickerType)

    The ``errors`` list is empty on success; ``ok`` is always present so
    callers can branch on a single boolean field.
    """

    ok = graphene.Boolean(
        required=True,
        description="True when the mutation completed without errors.",
    )
    message = graphene.String(
        required=True,
        description="Human-readable status message.",
    )
    errors = graphene.List(
        graphene.NonNull(ValidationError),
        required=True,
        description="Field-level validation errors (empty on success).",
    )


# ---------------------------------------------------------------------------
# Transaction types
# ---------------------------------------------------------------------------


class TransactionListPayloadType(graphene.ObjectType):
    items = graphene.List(TransactionTypeObject, required=True)
    pagination = graphene.Field(PaginationType, required=True)


class TransactionSummaryPayloadType(graphene.ObjectType):
    month = graphene.String(required=True)
    income_total = DecimalScalar(required=True)
    expense_total = DecimalScalar(required=True)
    items = graphene.List(TransactionTypeObject, required=True)
    pagination = graphene.Field(PaginationType, required=True)


class TransactionDueCountsType(graphene.ObjectType):
    total_transactions = graphene.Int(required=True)
    income_transactions = graphene.Int(required=True)
    expense_transactions = graphene.Int(required=True)


class TransactionDueRangePayloadType(graphene.ObjectType):
    items = graphene.List(TransactionTypeObject, required=True)
    counts = graphene.Field(TransactionDueCountsType, required=True)
    pagination = graphene.Field(PaginationType, required=True)


class DashboardStatusCountsType(graphene.ObjectType):
    paid = graphene.Int(required=True)
    pending = graphene.Int(required=True)
    cancelled = graphene.Int(required=True)
    postponed = graphene.Int(required=True)
    overdue = graphene.Int(required=True)


class DashboardCountsType(graphene.ObjectType):
    total_transactions = graphene.Int(required=True)
    income_transactions = graphene.Int(required=True)
    expense_transactions = graphene.Int(required=True)
    status = graphene.Field(DashboardStatusCountsType, required=True)


class DashboardTotalsType(graphene.ObjectType):
    income_total = DecimalScalar(required=True)
    expense_total = DecimalScalar(required=True)
    balance = DecimalScalar(required=True)


class DashboardCategoryType(graphene.ObjectType):
    tag_id = graphene.String()
    category_name = graphene.String(required=True)
    total_amount = DecimalScalar(required=True)
    transactions_count = graphene.Int(required=True)


class DashboardCategoriesType(graphene.ObjectType):
    expense = graphene.List(DashboardCategoryType, required=True)
    income = graphene.List(DashboardCategoryType, required=True)


class TransactionDashboardPayloadType(graphene.ObjectType):
    month = graphene.String(required=True)
    totals = graphene.Field(DashboardTotalsType, required=True)
    counts = graphene.Field(DashboardCountsType, required=True)
    top_categories = graphene.Field(DashboardCategoriesType, required=True)


class GoalTypeObject(graphene.ObjectType):
    id = graphene.ID(required=True)
    title = graphene.String(required=True)
    description = graphene.String()
    category = graphene.String()
    target_amount = graphene.String(required=True)
    current_amount = graphene.String(required=True)
    priority = graphene.Int(required=True)
    target_date = graphene.String()
    status = graphene.String(required=True)
    created_at = graphene.String()
    updated_at = graphene.String()


class GoalListPayloadType(graphene.ObjectType):
    items = graphene.List(GoalTypeObject, required=True)
    pagination = graphene.Field(PaginationType, required=True)


class GoalRecommendationType(graphene.ObjectType):
    priority = graphene.String(required=True)
    title = graphene.String(required=True)
    action = graphene.String(required=True)
    estimated_date = graphene.String()


class GoalPlanType(graphene.ObjectType):
    horizon = graphene.String(required=True)
    remaining_amount = graphene.String(required=True)
    capacity_amount = graphene.String(required=True)
    projected_monthly_contribution = graphene.String(required=True)
    recommended_monthly_contribution = graphene.String(required=True)
    months_to_goal = graphene.Int()
    months_until_target_date = graphene.Int()
    estimated_completion_date = graphene.String()
    target_date = graphene.String()
    goal_health = graphene.String(required=True)
    recommendations = graphene.List(GoalRecommendationType, required=True)


class InstallmentVsCashIndicatorSnapshotType(graphene.ObjectType):
    preset_type = graphene.String(required=True)
    source = graphene.String(required=True)
    annual_rate_percent = graphene.String(required=True)
    as_of = graphene.String(required=True)


class InstallmentVsCashComparisonType(graphene.ObjectType):
    cash_option_total = graphene.String(required=True)
    installment_option_total = graphene.String(required=True)
    installment_present_value = graphene.String(required=True)
    installment_real_value_today = graphene.String(required=True)
    present_value_delta_vs_cash = graphene.String(required=True)
    absolute_delta_vs_cash = graphene.String(required=True)
    relative_delta_vs_cash_percent = graphene.String(required=True)
    break_even_discount_percent = graphene.String(required=True)
    break_even_opportunity_rate_annual = graphene.String(required=True)


class InstallmentVsCashCashOptionType(graphene.ObjectType):
    total = graphene.String(required=True)


class InstallmentVsCashInstallmentOptionType(graphene.ObjectType):
    count = graphene.Int(required=True)
    amounts = graphene.List(graphene.String, required=True)
    installment_amount = graphene.String(required=True)
    nominal_total = graphene.String(required=True)
    upfront_fees = graphene.String(required=True)
    first_payment_delay_days = graphene.Int(required=True)


class InstallmentVsCashOptionsType(graphene.ObjectType):
    cash = graphene.Field(InstallmentVsCashCashOptionType, required=True)
    installment = graphene.Field(
        InstallmentVsCashInstallmentOptionType,
        required=True,
    )


class InstallmentVsCashNeutralityBandType(graphene.ObjectType):
    absolute_brl = graphene.String(required=True)
    relative_percent = graphene.String(required=True)


class InstallmentVsCashAssumptionsType(graphene.ObjectType):
    opportunity_rate_type = graphene.String(required=True)
    opportunity_rate_annual_percent = graphene.String(required=True)
    inflation_rate_annual_percent = graphene.String(required=True)
    periodicity = graphene.String(required=True)
    first_payment_delay_days = graphene.Int(required=True)
    upfront_fees_apply_to = graphene.String(required=True)
    neutrality_rule = graphene.String(required=True)


class InstallmentVsCashScheduleItemType(graphene.ObjectType):
    installment_number = graphene.Int(required=True)
    due_in_days = graphene.Int(required=True)
    amount = graphene.String(required=True)
    present_value = graphene.String(required=True)
    real_value_today = graphene.String(required=True)
    cumulative_nominal = graphene.String(required=True)
    cumulative_present_value = graphene.String(required=True)
    cumulative_real_value_today = graphene.String(required=True)
    cash_cumulative = graphene.String(required=True)


class InstallmentVsCashResultType(graphene.ObjectType):
    recommended_option = graphene.String(required=True)
    recommendation_reason = graphene.String(required=True)
    formula_explainer = graphene.String(required=True)
    comparison = graphene.Field(InstallmentVsCashComparisonType, required=True)
    options = graphene.Field(InstallmentVsCashOptionsType, required=True)
    neutrality_band = graphene.Field(
        InstallmentVsCashNeutralityBandType,
        required=True,
    )
    assumptions = graphene.Field(InstallmentVsCashAssumptionsType, required=True)
    indicator_snapshot = graphene.Field(InstallmentVsCashIndicatorSnapshotType)
    schedule = graphene.List(InstallmentVsCashScheduleItemType, required=True)


class InstallmentVsCashInputType(graphene.ObjectType):
    cash_price = graphene.String(required=True)
    installment_count = graphene.Int(required=True)
    installment_amount = graphene.String(required=True)
    installment_total = graphene.String(required=True)
    first_payment_delay_days = graphene.Int(required=True)
    opportunity_rate_type = graphene.String(required=True)
    opportunity_rate_annual = graphene.String(required=True)
    inflation_rate_annual = graphene.String(required=True)
    fees_upfront = graphene.String(required=True)
    scenario_label = graphene.String()


class InstallmentVsCashCalculationPayloadType(graphene.ObjectType):
    tool_id = graphene.String(required=True)
    rule_version = graphene.String(required=True)
    input = graphene.Field(InstallmentVsCashInputType, required=True)
    result = graphene.Field(InstallmentVsCashResultType, required=True)


class InstallmentVsCashSimulationType(graphene.ObjectType):
    id = graphene.ID(required=True)
    user_id = graphene.String()
    tool_id = graphene.String(required=True)
    rule_version = graphene.String(required=True)
    input = graphene.Field(InstallmentVsCashInputType, required=True)
    result = graphene.Field(InstallmentVsCashResultType, required=True)
    saved = graphene.Boolean(required=True)
    goal_id = graphene.String()
    created_at = graphene.String(required=True)


class SaveInstallmentVsCashSimulationPayloadType(graphene.ObjectType):
    message = graphene.String(required=True)
    simulation = graphene.Field(InstallmentVsCashSimulationType, required=True)
    calculation = graphene.Field(
        InstallmentVsCashCalculationPayloadType,
        required=True,
    )


class CreateGoalFromInstallmentVsCashSimulationPayloadType(graphene.ObjectType):
    message = graphene.String(required=True)
    goal = graphene.Field(GoalTypeObject, required=True)
    simulation = graphene.Field(InstallmentVsCashSimulationType, required=True)


class CreatePlannedExpenseFromInstallmentVsCashSimulationPayloadType(
    graphene.ObjectType
):
    message = graphene.String(required=True)
    transactions = graphene.List(TransactionTypeObject, required=True)
    simulation = graphene.Field(InstallmentVsCashSimulationType, required=True)


class WalletType(graphene.ObjectType):
    id = graphene.ID(required=True)
    name = graphene.String(required=True)
    value = DecimalScalar()
    estimated_value_on_create_date = DecimalScalar()
    ticker = graphene.String()
    quantity = graphene.Int()
    asset_class = graphene.String(required=True)
    annual_rate = DecimalScalar()
    register_date = graphene.String(required=True)
    target_withdraw_date = graphene.String()
    should_be_on_wallet = graphene.Boolean(required=True)


class WalletHistoryItemType(graphene.ObjectType):
    original_quantity = DecimalScalar()
    original_value = DecimalScalar()
    change_type = graphene.String()
    change_date = graphene.String()


class WalletHistoryPayloadType(graphene.ObjectType):
    items = graphene.List(WalletHistoryItemType, required=True)
    pagination = graphene.Field(PaginationType, required=True)


class WalletListPayloadType(graphene.ObjectType):
    items = graphene.List(WalletType, required=True)
    pagination = graphene.Field(PaginationType, required=True)


class InvestmentOperationType(graphene.ObjectType):
    id = graphene.ID(required=True)
    wallet_id = graphene.ID(required=True)
    user_id = graphene.ID(required=True)
    operation_type = graphene.String(required=True)
    quantity = graphene.String(required=True)
    unit_price = graphene.String(required=True)
    fees = graphene.String(required=True)
    executed_at = graphene.String(required=True)
    notes = graphene.String()
    created_at = graphene.String()
    updated_at = graphene.String()


class InvestmentOperationListPayloadType(graphene.ObjectType):
    items = graphene.List(InvestmentOperationType, required=True)
    pagination = graphene.Field(PaginationType, required=True)


class InvestmentOperationSummaryType(graphene.ObjectType):
    total_operations = graphene.Int(required=True)
    buy_operations = graphene.Int(required=True)
    sell_operations = graphene.Int(required=True)
    buy_quantity = graphene.String(required=True)
    sell_quantity = graphene.String(required=True)
    net_quantity = graphene.String(required=True)
    gross_buy_amount = graphene.String(required=True)
    gross_sell_amount = graphene.String(required=True)
    average_buy_price = graphene.String(required=True)
    total_fees = graphene.String(required=True)


class InvestmentPositionType(graphene.ObjectType):
    total_operations = graphene.Int(required=True)
    buy_operations = graphene.Int(required=True)
    sell_operations = graphene.Int(required=True)
    total_buy_quantity = graphene.String(required=True)
    total_sell_quantity = graphene.String(required=True)
    current_quantity = graphene.String(required=True)
    current_cost_basis = graphene.String(required=True)
    average_cost = graphene.String(required=True)


class InvestmentInvestedAmountType(graphene.ObjectType):
    date = graphene.String(required=True)
    total_operations = graphene.Int(required=True)
    buy_operations = graphene.Int(required=True)
    sell_operations = graphene.Int(required=True)
    buy_amount = graphene.String(required=True)
    sell_amount = graphene.String(required=True)
    net_invested_amount = graphene.String(required=True)


class PortfolioValuationItemType(graphene.ObjectType):
    investment_id = graphene.ID(required=True)
    name = graphene.String(required=True)
    asset_class = graphene.String(required=True)
    annual_rate = graphene.String()
    ticker = graphene.String()
    should_be_on_wallet = graphene.Boolean(required=True)
    quantity = graphene.String(required=True)
    unit_price = graphene.String(required=True)
    invested_amount = graphene.String(required=True)
    current_value = graphene.String(required=True)
    profit_loss_amount = graphene.String(required=True)
    profit_loss_percent = graphene.String(required=True)
    market_price = graphene.String()
    valuation_source = graphene.String(required=True)
    uses_operations_quantity = graphene.Boolean(required=True)


class PortfolioValuationSummaryType(graphene.ObjectType):
    total_investments = graphene.Int(required=True)
    with_market_data = graphene.Int(required=True)
    without_market_data = graphene.Int(required=True)
    total_invested_amount = graphene.String(required=True)
    total_current_value = graphene.String(required=True)
    total_profit_loss = graphene.String(required=True)
    total_profit_loss_percent = graphene.String(required=True)


class PortfolioValuationPayloadType(graphene.ObjectType):
    summary = graphene.Field(PortfolioValuationSummaryType, required=True)
    items = graphene.List(PortfolioValuationItemType, required=True)


class PortfolioHistoryItemType(graphene.ObjectType):
    date = graphene.String(required=True)
    total_operations = graphene.Int(required=True)
    buy_operations = graphene.Int(required=True)
    sell_operations = graphene.Int(required=True)
    buy_amount = graphene.String(required=True)
    sell_amount = graphene.String(required=True)
    net_invested_amount = graphene.String(required=True)
    cumulative_net_invested = graphene.String(required=True)
    total_current_value_estimate = graphene.String(required=True)
    total_profit_loss_estimate = graphene.String(required=True)


class PortfolioHistorySummaryType(graphene.ObjectType):
    start_date = graphene.String(required=True)
    end_date = graphene.String(required=True)
    total_points = graphene.Int(required=True)
    total_buy_amount = graphene.String(required=True)
    total_sell_amount = graphene.String(required=True)
    total_net_invested_amount = graphene.String(required=True)
    final_cumulative_net_invested = graphene.String(required=True)
    final_total_current_value_estimate = graphene.String(required=True)
    final_total_profit_loss_estimate = graphene.String(required=True)


class PortfolioHistoryPayloadType(graphene.ObjectType):
    summary = graphene.Field(PortfolioHistorySummaryType, required=True)
    items = graphene.List(PortfolioHistoryItemType, required=True)


class TickerType(graphene.ObjectType):
    id = graphene.ID(required=True)
    symbol = graphene.String(required=True)
    quantity = graphene.Float(required=True)
    type = graphene.String()


class TickerListPayloadType(graphene.ObjectType):
    items = graphene.List(TickerType, required=True)
    pagination = graphene.Field(PaginationType, required=True)


# ---------------------------------------------------------------------------
# Budget types (H-PROD-04 / #886)
# ---------------------------------------------------------------------------


class BudgetType(graphene.ObjectType):
    id = graphene.ID(required=True)
    name = graphene.String(required=True)
    amount = graphene.String(required=True)
    period = graphene.String(required=True)
    tag_id = graphene.String()
    tag_name = graphene.String()
    tag_color = graphene.String()
    start_date = graphene.String()
    end_date = graphene.String()
    is_active = graphene.Boolean(required=True)
    spent = graphene.String(required=True)
    remaining = graphene.String(required=True)
    percentage_used = graphene.Float(required=True)
    is_over_budget = graphene.Boolean(required=True)
    created_at = graphene.String()
    updated_at = graphene.String()


class BudgetListPayloadType(graphene.ObjectType):
    items = graphene.List(BudgetType, required=True)


class BudgetSummaryType(graphene.ObjectType):
    total_budgeted = graphene.String(required=True)
    total_spent = graphene.String(required=True)
    total_remaining = graphene.String(required=True)
    percentage_used = graphene.Float(required=True)
    budget_count = graphene.Int(required=True)


# ---------------------------------------------------------------------------
# Subscription types (H-P3.1 / #835)
# ---------------------------------------------------------------------------


class PlanFeatureType(graphene.ObjectType):
    key = graphene.String(required=True)
    label = graphene.String(required=True)


class BillingPlanType(graphene.ObjectType):
    slug = graphene.String(required=True)
    plan_code = graphene.String(required=True)
    display_name = graphene.String(required=True)
    description = graphene.String(required=True)
    price_cents = graphene.Int(required=True)
    currency = graphene.String(required=True)
    billing_cycle = graphene.String(required=True)
    is_active = graphene.Boolean(required=True)
    features = graphene.List(graphene.String, required=True)


class BillingPlanListPayloadType(graphene.ObjectType):
    plans = graphene.List(BillingPlanType, required=True)


class SubscriptionType(graphene.ObjectType):
    id = graphene.ID(required=True)
    plan_code = graphene.String(required=True)
    offer_code = graphene.String()
    status = graphene.String(required=True)
    billing_cycle = graphene.String()
    provider = graphene.String()
    provider_subscription_id = graphene.String()
    trial_ends_at = graphene.String()
    current_period_start = graphene.String()
    current_period_end = graphene.String()
    canceled_at = graphene.String()
    created_at = graphene.String()
    updated_at = graphene.String()


class CheckoutSessionType(graphene.ObjectType):
    checkout_url = graphene.String(required=True)
    provider = graphene.String(required=True)
    provider_customer_id = graphene.String()
    provider_subscription_id = graphene.String()


# ---------------------------------------------------------------------------
# Notification preference types (H-P3.3 / #836)
# ---------------------------------------------------------------------------


class AlertPreferenceType(graphene.ObjectType):
    category = graphene.String(required=True)
    enabled = graphene.Boolean(required=True)
    global_opt_out = graphene.Boolean(required=True)


class NotificationPreferencesType(graphene.ObjectType):
    preferences = graphene.List(AlertPreferenceType, required=True)


# ---------------------------------------------------------------------------
# Weekly summary types (B13 — MVP1 Dashboard)
# ---------------------------------------------------------------------------


class WeeklyPeriodTotalsType(graphene.ObjectType):
    start = graphene.String(required=True)
    end = graphene.String(required=True)
    income = DecimalScalar(required=True)
    expense = DecimalScalar(required=True)
    balance = DecimalScalar(required=True)
    transaction_count = graphene.Int(required=True)


class WeeklyComparisonType(graphene.ObjectType):
    income_delta = DecimalScalar(required=True)
    income_delta_percent = graphene.Float()
    expense_delta = DecimalScalar(required=True)
    expense_delta_percent = graphene.Float()
    balance_delta = DecimalScalar(required=True)
    balance_delta_percent = graphene.Float()


class WeeklySummarySeriesEntryType(graphene.ObjectType):
    date = graphene.String(required=True)
    income = DecimalScalar(required=True)
    expense = DecimalScalar(required=True)
    balance = DecimalScalar(required=True)


class WeeklySummaryPayloadType(graphene.ObjectType):
    current_week = graphene.Field(WeeklyPeriodTotalsType, required=True)
    previous_week = graphene.Field(WeeklyPeriodTotalsType, required=True)
    comparison = graphene.Field(WeeklyComparisonType, required=True)
    series = graphene.List(WeeklySummarySeriesEntryType, required=True)
    period = graphene.String(required=True)
    series_start = graphene.String(required=True)
    series_end = graphene.String(required=True)


# ---------------------------------------------------------------------------
# Tags (#1148 — GraphQL parity with REST /tags)
# ---------------------------------------------------------------------------


class TagType(graphene.ObjectType):
    id = graphene.ID(required=True)
    name = graphene.String(required=True)
    color = graphene.String()
    icon = graphene.String()


class TagListType(graphene.ObjectType):
    tags = graphene.List(graphene.NonNull(TagType), required=True)
    total = graphene.Int(required=True)


class TagPayload(MutationPayload):
    data = graphene.Field(TagType)


# ---------------------------------------------------------------------------
# Accounts (#1148 — GraphQL parity with REST /accounts)
# ---------------------------------------------------------------------------


class AccountType(graphene.ObjectType):
    id = graphene.ID(required=True)
    name = graphene.String(required=True)
    account_type = graphene.String(required=True)
    institution = graphene.String()
    initial_balance = DecimalScalar()


class AccountListType(graphene.ObjectType):
    accounts = graphene.List(graphene.NonNull(AccountType), required=True)
    total = graphene.Int(required=True)


class AccountPayload(MutationPayload):
    data = graphene.Field(AccountType)


# ---------------------------------------------------------------------------
# Bank Statement Import (#1148 — GraphQL surface for bank_import_service)
# ---------------------------------------------------------------------------


class BankImportPreviewEntryType(graphene.ObjectType):
    external_id = graphene.String(required=True)
    date = graphene.String(required=True)
    description = graphene.String(required=True)
    amount = graphene.String(required=True)
    transaction_type = graphene.String(required=True)
    bank_name = graphene.String(required=True)
    is_duplicate = graphene.Boolean(required=True)
    duplicate_reason = graphene.String()


class BankImportPreviewType(graphene.ObjectType):
    bank_name = graphene.String(required=True)
    entries = graphene.List(graphene.NonNull(BankImportPreviewEntryType), required=True)
    total_entries = graphene.Int(required=True)
    duplicate_entries = graphene.Int(required=True)
    new_entries = graphene.Int(required=True)


class BankImportPreviewPayload(MutationPayload):
    data = graphene.Field(BankImportPreviewType)


class ImportedTransactionType(graphene.ObjectType):
    id = graphene.ID(required=True)
    title = graphene.String(required=True)
    amount = graphene.String(required=True)
    type = graphene.String(required=True)
    due_date = graphene.String(required=True)
    bank_name = graphene.String()
    external_id = graphene.String()


class BankImportConfirmationPayload(MutationPayload):
    bank_name = graphene.String()
    month = graphene.String()
    imported_count = graphene.Int()
    skipped_duplicates = graphene.Int()
    replaced_count = graphene.Int()
    transactions = graphene.List(graphene.NonNull(ImportedTransactionType))


# ---------------------------------------------------------------------------
# Fiscal domain (#1247 — GraphQL parity with REST /fiscal/*)
# ---------------------------------------------------------------------------


class FiscalDocumentType(graphene.ObjectType):
    id = graphene.ID(required=True)
    external_id = graphene.String(required=True)
    type = graphene.String(required=True)
    status = graphene.String(required=True)
    issued_at = graphene.String(required=True)
    counterparty = graphene.String(required=True)
    gross_amount = DecimalScalar(required=True)
    currency = graphene.String(required=True)
    description = graphene.String()
    created_at = graphene.String(required=True)


class FiscalDocumentListType(graphene.ObjectType):
    fiscal_documents = graphene.List(
        graphene.NonNull(FiscalDocumentType), required=True
    )
    total = graphene.Int(required=True)


class FiscalDocumentPayload(MutationPayload):
    data = graphene.Field(FiscalDocumentType)


class ReceivableEntryType(graphene.ObjectType):
    """
    IMPORTANT: expected_net_amount is advisory-only. Clients MUST display
    the ``disclaimer`` field alongside any monetary value derived from it.
    """

    id = graphene.ID(required=True)
    fiscal_document_id = graphene.ID(required=True)
    expected_net_amount = DecimalScalar()
    received_amount = DecimalScalar()
    outstanding_amount = DecimalScalar()
    reconciliation_status = graphene.String(required=True)
    received_at = graphene.String()
    created_at = graphene.String(required=True)
    disclaimer = graphene.String(required=True)


class ReceivableListType(graphene.ObjectType):
    receivables = graphene.List(graphene.NonNull(ReceivableEntryType), required=True)
    total = graphene.Int(required=True)


class ReceivablePayload(MutationPayload):
    data = graphene.Field(ReceivableEntryType)


class ReceivableSummaryType(graphene.ObjectType):
    """
    IMPORTANT: all monetary values are advisory-only estimates.
    Always display the ``disclaimer`` field.
    """

    expected_total = graphene.String(required=True)
    received_total = graphene.String(required=True)
    pending_total = graphene.String(required=True)
    disclaimer = graphene.String(required=True)
