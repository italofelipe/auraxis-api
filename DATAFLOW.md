# Data Flow - auraxis-api

## Card Expense Creation

1. Client sends `POST /transactions` with `credit_card_id` and `impact_policy`.
2. `TransactionSchema` validates and normalizes the policy.
3. `execute_create_transaction` builds one transaction or an installment batch.
4. Each created row stores the same `impact_policy`.
5. Transaction serialization returns `impact_policy` to REST and GraphQL callers.

## Dashboard and Budgets

1. Dashboard overview/month summary/trends use `TransactionAnalyticsService`.
2. Budget spent calculations use `BudgetService.get_spent_for_budget`.
3. Both paths exclude `TransactionImpactPolicy.CARDS_ONLY`.
4. `planned_until_bill` remains included unless future planning semantics require a separate forecast surface.

## Card Bill and Utilization

1. Card bill reads `Transaction.credit_card_id`, cycle dates and status.
2. Card utilization sums the open cycle for pending/overdue/paid card transactions.
3. Neither path excludes `cards_only`, so the card remains financially accurate even when budgets ignore the purchase.

## Live Verification

`scripts/test_credit_card_impact_policy_live_db.sh` validates this flow in PostgreSQL: it creates a user, two cards, a budget, `full` and `cards_only` launches, then asserts that budgets ignore `cards_only`, card bills include both policies and `GET /transactions?credit_card_id=...` scopes results to the selected card.
