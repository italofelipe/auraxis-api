# Data Flow - auraxis-api

## Account block and session revocation

1. FastAPI v2 persists an idempotent administrative action, then updates the v1 identity
   through its restricted repository.
2. The v1 user receives `blocked_at`, `blocked_reason` and `blocked_by`; all refresh-token
   families are revoked and current access/refresh JTI fields are cleared.
3. Revocation caches are invalidated. Existing bearer tokens are rejected by the request guard,
   while login and refresh reject only after credential/token validation with
   `ACCOUNT_BLOCKED`.
4. Unblock clears block metadata but does not restore any JTI, so a new login is required.

## Premium override

1. The control plane grants or revokes one `premium_overrides` row with actor, reason and
   optional future expiry; `subscriptions` is not updated.
2. Entitlement checks treat an active override as access to the current premium feature set.
3. Cache entries never live beyond the earliest entitlement/override expiry.
4. `/subscriptions/me` returns the billing subscription unchanged plus
   `effective_access: premium|free` for cross-version consumers.
5. During migration, configured environment IDs are converted to the same audited rows by
   `flask premium-overrides migrate-env`; a missing configured user fails the command.

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
