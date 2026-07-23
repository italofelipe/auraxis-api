# Backoffice account controls (v1 enforcement)

## Schema

Migration `bo1_account_controls` adds nullable block/last-login fields to `users` and creates
`premium_overrides`. Existing users remain unblocked. Overrides contain grant/revoke timestamps,
reason, optional expiry and operator identifiers, and are deliberately independent of billing.

## Authentication behavior

- Valid credentials for a blocked account return 403 with `ACCOUNT_BLOCKED`.
- Refresh, authenticated REST and authenticated GraphQL enforce the same state.
- A block revokes all stored session families and invalidates revocation caches.
- An unblock clears the block fields only; old tokens remain revoked.

This ordering avoids leaking account existence for invalid credentials while making the state
clear to a legitimate blocked user.

## Migrating legacy premium IDs

Before removing `AURAXIS_PREMIUM_OVERRIDE_USER_IDS`, run:

```bash
flask --app run premium-overrides migrate-env --dry-run
flask --app run premium-overrides migrate-env
```

The command is idempotent. It leaves subscriptions and provider state unchanged, creates a
permanent audited override for each existing configured user and exits non-zero when any ID is
missing. Remove the environment fallback only after comparing the configured count with the
created/existing count and validating premium gates.

## Release verification

```bash
bash scripts/test_migrations_local.sh
pytest -q tests/test_backoffice_account_controls.py tests/test_premium_override_entitlement.py
```

In staging, create independent v1/v2 identities with the same verified email, block the person,
and confirm login, refresh, REST and GraphQL denial. Then unblock and verify that a new login is
required. Grant/revoke an override and verify that the subscription row is byte-for-byte
unchanged.
