# Credit Cards Impact Policy

## Decision

Credit-card launches are stored as transactions. The system does not introduce a second card-expense table for this flow.

The `impact_policy` field decides how a card transaction propagates:

| Value | Cards/fatura | Transaction list | Dashboard | Budgets |
| --- | --- | --- | --- | --- |
| `full` | yes | yes | yes | yes |
| `cards_only` | yes | yes | no | no |
| `planned_until_bill` | yes | yes | yes | yes |

## API Contract

`POST /transactions` and `PATCH /transactions/{id}` accept:

```json
{
  "impact_policy": "cards_only"
}
```

Default is `full` for backward compatibility.

`GET /transactions`, transaction details and credit-card bill payloads include `impact_policy`.

## Implemented Tests

- Transaction create/update/installments persist policy.
- Invalid policy is rejected.
- Dashboard overview ignores `cards_only`.
- Budgets ignore `cards_only`.
- Card bill still includes `cards_only`.
- `tests/test_credit_card_impact_policy_live_db.py` verifies policy, bill, budget and `credit_card_id` filtering against real PostgreSQL.
- Existing bill cycle and bill endpoint tests remain green.

Run the live database check with:

```bash
FLASK_CMD=flask PYTEST_CMD=pytest scripts/test_credit_card_impact_policy_live_db.sh
```

The script starts an ephemeral `postgres:16` container, applies Alembic migrations and removes the container at the end.

## Follow-ups

- Add richer card analytics endpoint for category/time series.
- Decide if `planned_until_bill` should move from dashboard inclusion to a dedicated forecast lane.
- Add staging DB migration smoke before release promotion.
