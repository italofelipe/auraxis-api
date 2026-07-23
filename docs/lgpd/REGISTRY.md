# LGPD Registry — How to Register New Models

The LGPD registry (`app/lgpd/registry.py`) is the **technical source of truth**
for every entity that stores personal data in the backend. It drives the
export endpoint (`/user/me/export`), account-deletion behaviour
(`DELETE /user/me`), AI/LLM minimisation tracking, and the CI guard that
prevents new user-data tables from being silently introduced.

---

## When to Register

Any new SQLAlchemy model that exposes one of the following columns **must**
be registered:

- `user_id` — standard FK to `users.id`
- `owner_id` — used by `SharedEntry` for the owner side of a shared transaction
- `from_user_id` / `to_user_id` — used by `Invitation`
- The `User` model itself (the base personal entity)

The CI test
`tests/lgpd/test_registry.py::test_all_user_linked_models_are_registered`
walks `app.models` and **fails the build** if any user-linked model is missing
from the registry.

---

## How to Register

Add an `EntityRule` entry inside `_build_registry()` in
`app/lgpd/registry.py`:

```python
EntityRule(
    model=YourNewModel,
    user_id_field="user_id",          # column name linking to users.id
    table_name="your_new_table",      # must match __tablename__
    deletion_strategy=DeletionStrategy.DELETE,    # see below
    export_included=True,             # included in /user/me/export?
    retention_reason=RetentionReason.NONE,        # see below
    retention_days=None,              # None = no fixed retention
    description="One-line description of what this entity stores",
),
```

Import the model lazily at the top of `_build_registry()` (the function
imports are intentional — they prevent circular imports during app startup).

---

## Deletion Strategies

| Strategy   | Behaviour on account deletion                        | When to use |
|------------|------------------------------------------------------|-------------|
| `DELETE`   | Row is hard-deleted.                                 | Purely user-owned data with no legal retention obligation (transactions, goals, accounts, etc). |
| `ANONYMIZE`| Row is kept; PII fields are nulled or hashed.        | When foreign keys would break referential integrity, or when aggregate audit needs the structural row (audit events, subscription billing state). |
| `RETAIN`   | Row is kept entirely.                                | Only when a legal obligation overrides LGPD erasure (Brazilian fiscal documents, billing receipts). |

`RETAIN` always requires a `retention_reason != NONE` — the test
`test_retain_strategy_requires_retention_reason` enforces this.

---

## Retention Reasons

| Reason          | Typical window | Notes |
|-----------------|----------------|-------|
| `NONE`          | n/a            | Row dies with the user. Implies `retention_days=None`. |
| `FISCAL`        | 1825 days (5y) | Brazilian tax law minimum. |
| `AUDIT`         | 365 days       | Internal compliance audit. |
| `LGPD_PROCESS`  | indefinite     | Consent records, DSR response evidence. |
| `SECURITY`      | 90 days        | Security incident response window. |

The test `test_retention_days_consistent_with_reason` enforces that
`NONE` retention always carries `retention_days=None`.

---

## Invariants Enforced by Tests

`tests/lgpd/test_registry.py` enforces, for every entry:

- `table_name` matches the model's `__tablename__`
- `user_id_field` is a real column on the model
- `RETAIN` strategy carries a non-`NONE` retention reason
- `NONE` retention reason carries `retention_days=None`
- Every entry has a non-empty `description`
- No duplicate models, no duplicate table names
- `EntityRule` is frozen (immutable at runtime)

Critical entities (`users`, `transactions`, `llm_audit_logs`, `ai_insights`,
`refresh_tokens`, `push_subscriptions`, `shared_entries`, `fiscal_documents`,
`subscriptions`) must always be present. Manual premium overrides are exported
with the data subject package and deleted with the account; their cross-system
administrative audit remains in the v2 control plane under its own retention
policy.

---

## Common Pitfalls

- **Naming**: model class names may differ from filename — confirm with
  `__tablename__` rather than guessing.
- **Multiple models per file**: `fiscal.py` defines four classes; `alert.py`
  defines two; `shared_entry.py` defines two. Register **each** model that
  carries a user-linking column.
- **Non-user-linked tables**: `webhook_event` has no user link and is
  intentionally **not** in the registry.
- **`owner_id` / `from_user_id` / `to_user_id`**: these patterns are
  user-links too — the CI guard catches them.

---

## See Also

- Issue #1255 — this module (registry + guard)
- Issue #1256 — `/user/me/export` endpoint (consumes registry)
- Issue #1257 — auditable integral deletion (consumes registry)
- Issue #1258 — AI/LLM data minimisation (consumes registry)
- Issue #1259 — versioned consents
- `app/lgpd/registry.py` — the registry itself
- `tests/lgpd/test_registry.py` — invariants and CI gate
