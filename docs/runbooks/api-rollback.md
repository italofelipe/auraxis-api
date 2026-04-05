# API Rollback Procedure — Auraxis API

> **Audience:** On-call engineer / platform owner
> **Last updated:** 2026-04-05
> **Related:** `docs/runbooks/disaster-recovery.md`, `docs/RUNBOOK.md`

---

## When to Roll Back

Trigger a rollback when any of the following is observed after a deploy:

| Signal | How to detect |
|:-------|:-------------|
| Sentry error spike | Sentry → Auraxis API → Issues (sort by First Seen); spike immediately after deploy time |
| Health check failure | `curl -fsS https://api.auraxis.com.br/healthz` returns non-200 |
| Smoke test failure | POST `/graphql` with empty query returns 500 (expected: validation error) |
| Auth endpoint 500 | POST `/auth/login` with invalid credentials returns 500 (expected: 401) |
| CI smoke checks failing in GitHub Actions | Check the deploy workflow run in Actions tab |

---

## Step 1 — Identify the Bad Deploy

### Check deploy state on the instance

```bash
# Connect via SSM (no SSH required)
aws ssm start-session \
  --target i-0057e3b52162f78f8 \
  --region us-east-1 \
  --profile auraxis-admin

# Inside the session:
cat /var/lib/auraxis/deploy_state.json
```

The file contains:
- `current_ref` — the commit SHA currently deployed
- `previous_ref` — the commit SHA deployed before the current one

### Check Sentry for the error

1. Go to https://sentry.io → **Auraxis API** project
2. Filter Issues by **First Seen** — look for a spike aligned with the deploy timestamp
3. Open the issue to get the stack trace and affected endpoint

### Check recent commits

```bash
git -C repos/auraxis-api log --oneline -10 origin/master
```

---

## Step 2 — Roll Back

### Option A: Rollback via deploy script (fastest, recommended)

Uses the `previous_ref` stored in the deploy state file — no git access required on the instance:

```bash
./scripts/python_exec.sh scripts/aws_deploy_i6.py \
  --profile auraxis-admin \
  --region us-east-1 \
  rollback \
  --env prod
```

Expected output:
```
[deploy] Rolling back prod to previous_ref: <sha>
[deploy] Deploy successful. Health check: 200 OK
```

### Option B: git revert on master + re-deploy

Use when Option A is unavailable (state file corrupted, deploy script unreachable)
or when you want to permanently remove the bad commit from the release history.

```bash
# 1. Identify the bad commit SHA
git -C repos/auraxis-api log --oneline -5 origin/master

# 2. Create a revert commit (does NOT rewrite history)
git -C repos/auraxis-api revert <bad-commit-sha> --no-edit
git -C repos/auraxis-api push origin master

# 3. Deploy the revert
./scripts/python_exec.sh scripts/aws_deploy_i6.py \
  --profile auraxis-admin \
  --region us-east-1 \
  deploy \
  --env prod \
  --git-ref origin/master
```

> **Never use `git reset --hard` + force push on `master`.** Always revert to preserve
> history. See `.context/07_steering_global.md` — "Reescrever histórico compartilhado
> sem alinhamento explícito" is prohibited.

### Option C: Deploy a specific release tag

If the project uses release tags and you want to pin to a known-good release:

```bash
# List recent tags
git -C repos/auraxis-api tag --sort=-creatordate | head -10

# Deploy a specific tag
./scripts/python_exec.sh scripts/aws_deploy_i6.py \
  --profile auraxis-admin \
  --region us-east-1 \
  deploy \
  --env prod \
  --git-ref refs/tags/<tag-name>
```

---

## Step 3 — Verify Rollback Success

Run all checks after completing the rollback:

### Health check

```bash
curl -fsS https://api.auraxis.com.br/healthz
# Expected: {"status": "ok"} with HTTP 200
```

### GraphQL smoke

```bash
curl -s -X POST https://api.auraxis.com.br/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":""}' | python3 -m json.tool
# Expected: validation error (not 500 / INTERNAL_ERROR)
```

### Auth smoke

```bash
curl -s -X POST https://api.auraxis.com.br/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.com","password":"wrongpassword"}' \
  -w "\nHTTP %{http_code}\n"
# Expected: HTTP 401 (not 500)
```

### Check Sentry

Wait 3–5 minutes after rollback. The error rate for the previously-spiking issue
should drop to zero. If it continues, the bug may be in an older commit — investigate
`previous_ref` further.

### Check deploy state

```bash
# Via SSM
cat /var/lib/auraxis/deploy_state.json
# current_ref should now point to the pre-bad-deploy commit
```

---

## Step 4 — Post-Rollback Actions

- [ ] Open a GitHub issue (or update the existing one) describing the regression
- [ ] Link the bad commit SHA and the Sentry issue URL
- [ ] Add a regression test that covers the failing scenario before re-attempting the feature
- [ ] Update `TASKS.md` or GitHub Projects with the rollback event

---

## Quick Reference

| Action | Command |
|:-------|:--------|
| Check deploy state | `cat /var/lib/auraxis/deploy_state.json` (via SSM) |
| Rollback to previous | `scripts/aws_deploy_i6.py rollback --env prod` |
| Deploy specific ref | `scripts/aws_deploy_i6.py deploy --env prod --git-ref <ref>` |
| Health check | `curl -fsS https://api.auraxis.com.br/healthz` |
| View recent commits | `git log --oneline -10 origin/master` |
| View Sentry errors | https://sentry.io → Auraxis API → Issues |
