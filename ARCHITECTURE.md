# Architecture - auraxis-api

## Credit Card Impact Policy

Transactions remain the canonical source for both regular expenses and card expenses. A card launch is a `Transaction` with `credit_card_id` and an `impact_policy`.

`Transaction.impact_policy` values:

- `full`: canonical default. The transaction affects cards, transaction lists, dashboard and budgets.
- `cards_only`: the transaction affects card bill/utilization and remains visible in transaction lists, but is ignored by budget and dashboard aggregates.
- `planned_until_bill`: reserved for bill-aware planning flows where the transaction should remain explicit until the bill is settled.

The field is stored on `transactions` and exposed by REST, GraphQL legacy types, bill payloads and transaction serialization.

## Aggregate Boundaries

Card bill and utilization services intentionally do not filter by `impact_policy`; if a transaction is attached to a card and belongs to the cycle, it is part of the card reality.

Budget and dashboard aggregates exclude `cards_only`, because the user explicitly chose not to let that launch affect other financial surfaces.

## Migration

`migrations/versions/cc3_transaction_impact_policy.py` adds `transactions.impact_policy` with default `full` and a check constraint for accepted values.

`scripts/test_credit_card_impact_policy_live_db.sh` is the release-oriented smoke for this feature. It applies migrations to an ephemeral PostgreSQL database and exercises the REST flow for `impact_policy`, card bill inclusion, budget exclusion and `credit_card_id` transaction filtering.
