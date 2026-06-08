from __future__ import annotations

import graphene

from app.graphql.mutations.account import (
    CreateAccountMutation,
    DeleteAccountMutation,
    UpdateAccountMutation,
)
from app.graphql.mutations.ai_insight import (
    GenerateAiInsightMutation,
    SubmitAiInsightFeedbackMutation,
)
from app.graphql.mutations.auth import (
    ConfirmEmailMutation,
    ForgotPasswordMutation,
    LoginMutation,
    LogoutMutation,
    RegisterUserMutation,
    ResendConfirmationEmailMutation,
    ResetPasswordMutation,
    RevokeAllSessionsMutation,
    RevokeSessionMutation,
    UpdateUserProfileMutation,
)
from app.graphql.mutations.bank_statement import (
    ConfirmBankImportMutation,
    PreviewBankStatementMutation,
)
from app.graphql.mutations.budget import (
    CreateBudgetMutation,
    DeleteBudgetMutation,
    UpdateBudgetMutation,
)
from app.graphql.mutations.fiscal import (
    CancelReceivableMutation,
    CreateFiscalDocumentMutation,
    CreateReceivableMutation,
    MarkReceivableReceivedMutation,
)
from app.graphql.mutations.goal import (
    CreateGoalMutation,
    DeleteGoalMutation,
    SimulateGoalPlanMutation,
    UpdateGoalMutation,
)
from app.graphql.mutations.investment_operation import (
    AddInvestmentOperationMutation,
    DeleteInvestmentOperationMutation,
    UpdateInvestmentOperationMutation,
)
from app.graphql.mutations.notification import UpdateNotificationPreferencesMutation
from app.graphql.mutations.simulation import (
    ConsumeSimulationQuotaMutation,
    CreateGoalFromInstallmentVsCashSimulationMutation,
    CreatePlannedExpenseFromInstallmentVsCashSimulationMutation,
    SaveInstallmentVsCashSimulationMutation,
)
from app.graphql.mutations.subscription import (
    CancelSubscriptionMutation,
    CreateCheckoutSessionMutation,
)
from app.graphql.mutations.tag import (
    CreateTagMutation,
    DeleteTagMutation,
    UpdateTagMutation,
)
from app.graphql.mutations.ticker import AddTickerMutation, DeleteTickerMutation
from app.graphql.mutations.transaction import (
    CreateTransactionMutation,
    DeleteTransactionMutation,
    UpdateTransactionMutation,
)
from app.graphql.mutations.user import CompleteOnboardingMutation
from app.graphql.mutations.wallet import (
    AddWalletEntryMutation,
    DeleteWalletEntryMutation,
    UpdateWalletEntryMutation,
)


class Mutation(graphene.ObjectType):
    register_user = RegisterUserMutation.Field()
    login = LoginMutation.Field()
    logout = LogoutMutation.Field()
    forgot_password = ForgotPasswordMutation.Field()
    resend_confirmation_email = ResendConfirmationEmailMutation.Field()
    reset_password = ResetPasswordMutation.Field()
    confirm_email = ConfirmEmailMutation.Field()
    update_user_profile = UpdateUserProfileMutation.Field()
    # ADR-0002: CRUD mutations deprecated — use REST endpoints.
    # See docs/adr/0002-graphql-ownership.md for rationale and migration.
    create_transaction = CreateTransactionMutation.Field(
        deprecation_reason="ADR-0002: use POST /transactions"
    )
    update_transaction = UpdateTransactionMutation.Field(
        deprecation_reason="ADR-0002: use PATCH /transactions/{id}"
    )
    delete_transaction = DeleteTransactionMutation.Field(
        deprecation_reason="ADR-0002: use DELETE /transactions/{id}"
    )
    create_goal = CreateGoalMutation.Field(
        deprecation_reason="ADR-0002: use POST /goals"
    )
    update_goal = UpdateGoalMutation.Field(
        deprecation_reason="ADR-0002: use PATCH /goals/{id}"
    )
    delete_goal = DeleteGoalMutation.Field(
        deprecation_reason="ADR-0002: use DELETE /goals/{id}"
    )
    simulate_goal_plan = SimulateGoalPlanMutation.Field()
    save_installment_vs_cash_simulation = (
        SaveInstallmentVsCashSimulationMutation.Field()
    )
    create_goal_from_installment_vs_cash_simulation = (
        CreateGoalFromInstallmentVsCashSimulationMutation.Field()
    )
    create_planned_expense_from_installment_vs_cash_simulation = (
        CreatePlannedExpenseFromInstallmentVsCashSimulationMutation.Field()
    )
    consume_simulation_quota = ConsumeSimulationQuotaMutation.Field()
    # ADR-0002: CRUD mutations deprecated — use REST endpoints.
    add_wallet_entry = AddWalletEntryMutation.Field(
        deprecation_reason="ADR-0002: use POST /wallet"
    )
    update_wallet_entry = UpdateWalletEntryMutation.Field(
        deprecation_reason="ADR-0002: use PATCH /wallet/{id}"
    )
    delete_wallet_entry = DeleteWalletEntryMutation.Field(
        deprecation_reason="ADR-0002: use DELETE /wallet/{id}"
    )
    # ADR-0002: CRUD mutations deprecated — use REST endpoints.
    add_investment_operation = AddInvestmentOperationMutation.Field(
        deprecation_reason="ADR-0002: use POST /wallet/{id}/operations"
    )
    update_investment_operation = UpdateInvestmentOperationMutation.Field(
        deprecation_reason="ADR-0002: use PATCH /wallet/{id}/operations/{op_id}"
    )
    delete_investment_operation = DeleteInvestmentOperationMutation.Field(
        deprecation_reason="ADR-0002: use DELETE /wallet/{id}/operations/{op_id}"
    )
    add_ticker = AddTickerMutation.Field()
    delete_ticker = DeleteTickerMutation.Field()
    # Tags — canonical surface (no REST equivalent for bulk ops; CRUD exposed here)
    create_tag = CreateTagMutation.Field()
    update_tag = UpdateTagMutation.Field()
    delete_tag = DeleteTagMutation.Field()
    # Accounts — canonical surface
    create_account = CreateAccountMutation.Field()
    update_account = UpdateAccountMutation.Field()
    delete_account = DeleteAccountMutation.Field()
    # ADR-0002: CRUD mutations deprecated — use REST endpoints.
    create_budget = CreateBudgetMutation.Field(
        deprecation_reason="ADR-0002: use POST /budgets"
    )
    update_budget = UpdateBudgetMutation.Field(
        deprecation_reason="ADR-0002: use PATCH /budgets/{id}"
    )
    delete_budget = DeleteBudgetMutation.Field(
        deprecation_reason="ADR-0002: use DELETE /budgets/{id}"
    )
    # ADR-0004: subscription CRUD mutations deprecated — use REST endpoints.
    create_checkout_session = CreateCheckoutSessionMutation.Field(
        deprecation_reason="ADR-0004: use POST /subscription/checkout"
    )
    cancel_subscription = CancelSubscriptionMutation.Field(
        deprecation_reason="ADR-0004: use POST /subscription/cancel"
    )
    update_notification_preferences = UpdateNotificationPreferencesMutation.Field()
    revoke_session = RevokeSessionMutation.Field()
    revoke_all_sessions = RevokeAllSessionsMutation.Field()
    # Bank Statement Import — canonical GraphQL surface (#1148)
    preview_bank_statement = PreviewBankStatementMutation.Field()
    confirm_bank_import = ConfirmBankImportMutation.Field()
    # Fiscal domain (#1247) — ADR-0002: REST is canonical for writes
    create_receivable = CreateReceivableMutation.Field(
        deprecation_reason="ADR-0002: use POST /fiscal/receivables"
    )
    mark_receivable_received = MarkReceivableReceivedMutation.Field(
        deprecation_reason="ADR-0002: use PATCH /fiscal/receivables/{id}/receive"
    )
    cancel_receivable = CancelReceivableMutation.Field(
        deprecation_reason="ADR-0002: use DELETE /fiscal/receivables/{id}"
    )
    create_fiscal_document = CreateFiscalDocumentMutation.Field(
        deprecation_reason="ADR-0002: use POST /fiscal/fiscal-documents"
    )
    # AI Advisory — canonical GraphQL parity for POST /ai/insights/generate
    generate_ai_insight = GenerateAiInsightMutation.Field()
    submit_ai_insight_feedback = SubmitAiInsightFeedbackMutation.Field()
    # Onboarding completion — REST parity: POST /user/onboarding/complete (#1471)
    complete_onboarding = CompleteOnboardingMutation.Field()


__all__ = ["Mutation"]
