# Feature Flags + Canary Deploy

## Overview

Auraxis uses a Redis-backed feature flag system that enables:

- Toggling features on/off without redeploying
- Progressive canary rollouts by user cohort (deterministic %)
- Instant kill switches (< 60s propagation)
- Management via Flask CLI and HTTP admin API

## Architecture

### Redis Key Schema

```
auraxis:flags:<flag_name>  →  JSON (no TTL — persistent until deleted)
```

Payload structure:

```json
{
  "enabled": true,
  "canary_percentage": 10,
  "description": "FGTS simulator — 10% canary",
  "updated_at": "2026-04-01T12:00:00+00:00"
}
```

### Canary Evaluation Logic

```
canary_percentage == 0    → flag is ON for 100% of users
canary_percentage == 100  → flag is ON for 100% of users
1 <= pct <= 99            → hash(f"{flag_name}:{user_id}") % 100 < pct
user_id is None           → False (anonymous excluded from canary)
Redis unavailable         → False (fail-closed — safe default)
```

The hash is computed in-process and never stored, so no LGPD/GDPR implications beyond what the caller already holds.

## Service Usage

```python
from app.services.feature_flag_service import get_feature_flag_service

svc = get_feature_flag_service()

# Evaluate a flag for a specific user
if svc.is_enabled("tools.fgts_simulator", user_id=current_user_id):
    return run_fgts_simulator()

# Set/update a flag
svc.set_flag("tools.fgts_simulator", enabled=True, canary_percentage=10,
             description="10% canary rollout")

# Kill switch
svc.set_flag("tools.fgts_simulator", enabled=False)
# or:
svc.delete_flag("tools.fgts_simulator")
```

## CLI Commands

```bash
# Seed a flag at 10% canary
flask features set tools.fgts_simulator --enabled --canary 10 --description "FGTS 10% pilot"

# Widen rollout to 50%
flask features set tools.fgts_simulator --canary 50

# Full rollout (canary=0 means everyone)
flask features set tools.fgts_simulator --canary 0

# Inspect a flag
flask features get tools.fgts_simulator

# List all flags
flask features list

# Kill switch — disable immediately
flask features set tools.fgts_simulator --disabled

# Remove flag entirely
flask features delete tools.fgts_simulator
```

## HTTP Admin API

All endpoints require a valid JWT. The blueprint is mounted under `/admin`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/feature-flags` | List all flags |
| `GET` | `/admin/feature-flags/<name>` | Get one flag |
| `POST` | `/admin/feature-flags` | Create or update a flag |
| `DELETE` | `/admin/feature-flags/<name>` | Delete a flag |

### POST body

```json
{
  "name": "tools.fgts_simulator",
  "enabled": true,
  "canary_percentage": 10,
  "description": "FGTS simulator pilot"
}
```

### Example responses

```jsonc
// GET /admin/feature-flags/tools.fgts_simulator
{
  "name": "tools.fgts_simulator",
  "enabled": true,
  "canary_percentage": 10,
  "description": "FGTS simulator pilot",
  "updated_at": "2026-04-01T12:00:00+00:00"
}
```

## Canary Deploy Workflow

### Step 1 — Seed flag (5% pilot)

```bash
flask features set tools.fgts_simulator --enabled --canary 5 \
  --description "FGTS simulator — phase 1 canary"
```

Or via SSM from your laptop (no SSH required):

```bash
aws ssm send-command \
  --instance-ids i-0057e3b52162f78f8 \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["cd /opt/auraxis && docker compose exec web flask features set tools.fgts_simulator --enabled --canary 5"]'
```

### Step 2 — Monitor

Check Sentry for new errors and CloudWatch for p95 latency. Target thresholds:

- Error rate: < 1%
- p95 latency: < 400 ms
- Healthz: HTTP 200

### Step 3 — Widen rollout

```bash
flask features set tools.fgts_simulator --canary 25
flask features set tools.fgts_simulator --canary 50
flask features set tools.fgts_simulator --canary 0  # 0 = full rollout
```

### Step 4 — Kill switch (rollback)

```bash
# Via CLI on the server
flask features set tools.fgts_simulator --disabled

# Via SSM from laptop (no SSH)
aws ssm send-command \
  --instance-ids i-0057e3b52162f78f8 \
  --document-name AWS-RunShellScript \
  --parameters "commands=[\"cd /opt/auraxis && docker compose exec web flask features set tools.fgts_simulator --disabled\"]"
echo "Flag disabled. Propagation within the next request cycle."
```

Propagation is immediate — no cache TTL on flags. The next request hitting the service will evaluate the updated value.

## Initial Flag Catalog

| Flag | Default | Description |
|------|---------|-------------|
| `tools.save_to_platform` | `false` | Save tool results to goals/budget |
| `tools.cta_trial` | `true` | Trial CTA for anonymous visitors |
| `tools.fgts_simulator` | `false` | FGTS withdrawal simulator |
| `tools.split_bill` | `false` | Bill splitting tool |
| `tools.overtime_calculator` | `false` | Overtime pay calculator |
| `tools.clt_termination` | `false` | CLT termination calculator |
| `tools.clt_vs_pj` | `false` | CLT vs PJ comparison |
| `tools.international_salary` | `false` | International salary tool |

## Graceful Degradation

When Redis is unavailable:

- `is_enabled()` returns `False` — fail-closed
- `set_flag()` logs a warning and returns silently
- `list_flags()` returns `{}`
- The application continues operating normally with all flags off

## LGPD / Privacy Notes

The canary hash `hash(f"{flag_name}:{user_id}") % 100` is:

- Computed in-memory only — never stored or logged
- One-way — the original `user_id` cannot be recovered from the bucket value
- Per-flag — different flags produce independent buckets for the same user

No additional LGPD obligation is introduced beyond what the caller already holds by having the `user_id` in scope.
