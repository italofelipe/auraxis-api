# Staging Deploy Runbook

## Overview

The staging environment runs on the dev EC2 instance (`i-0bddcfc8ea56c2ba3`) at
`dev.api.auraxis.com.br`. It uses the same SSM-based deploy mechanism as production
and acts as the mandatory validation gate before any code reaches production.

**Deploy flow:** feature branch → `staging` (automated CI) → manual PROD dispatch

---

## Environments

| Environment | Host                        | EC2 Instance        | Deploy trigger          |
|:------------|:----------------------------|:--------------------|:------------------------|
| staging     | dev.api.auraxis.com.br      | i-0bddcfc8ea56c2ba3 | push to `staging` branch |
| production  | api.auraxis.com.br          | (prod EC2)          | manual `workflow_dispatch` |

---

## Promoting Code: Feature Branch → Staging → Production

### Step 1 — Merge feature branch into staging

```bash
git checkout staging
git pull origin staging
git merge --no-ff origin/<your-feature-branch>
git push origin staging
```

Pushing to `staging` automatically triggers the **Deploy Staging** workflow in GitHub Actions.

### Step 2 — Monitor the staging deploy

1. Open the [Actions tab](https://github.com/italofelipe/auraxis-api/actions/workflows/deploy-staging.yml).
2. Watch the **Deploy Staging** run complete.
3. The workflow runs post-deploy smoke tests automatically. If they fail the deploy is
   rolled back and you will see a `failure` status on the GitHub Deployment.

### Step 3 — Promote to production

Once staging is green:

1. Ensure `staging` is merged into `master` (or cherry-pick if needed).
2. Go to **Actions → Deploy → Run workflow**.
3. Select `prod` as the target environment and provide the git ref if needed.
4. Monitor the **Deploy PROD** job and its **Readiness gate** step.

---

## Running the Staging Smoke Test Manually

The smoke test script can be run locally against any environment:

```bash
# Ensure the venv is active
source .venv/bin/activate

# Run against staging
python scripts/http_smoke_check.py \
  --env-name staging \
  --base-url http://dev.api.auraxis.com.br \
  --timeout 20
```

The script checks:

| Check                            | Endpoint                  | Expected          |
|:---------------------------------|:--------------------------|:------------------|
| REST health                      | GET /healthz              | HTTP 200          |
| GraphQL empty query              | POST /graphql             | HTTP 400 + VALIDATION_ERROR |
| REST invalid login               | POST /auth/login          | HTTP 400/401/429  |
| GraphQL invalid login            | POST /graphql             | HTTP 200 + error code (not INTERNAL_ERROR) |
| REST installment-vs-cash calc    | POST /simulations/...     | HTTP 200 + tool_id |
| GraphQL installment-vs-cash calc | POST /graphql             | HTTP 200 + toolId |

To check only `/healthz` and `/readiness` with curl:

```bash
BASE_URL="http://dev.api.auraxis.com.br"
for endpoint in /healthz /readiness; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "${BASE_URL}${endpoint}")
  echo "${endpoint}: HTTP ${STATUS}"
done
```

---

## Rollback

If a staging deploy fails the workflow auto-rolls back using `aws_deploy_i6.py rollback --env dev`.

To roll back staging manually:

```bash
# Requires AWS credentials with SSM SendCommand permissions on the dev EC2
python scripts/aws_deploy_i6.py \
  --profile "" \
  --region <AWS_REGION> \
  --dev-instance-id i-0bddcfc8ea56c2ba3 \
  --prod-instance-id <PROD_INSTANCE_ID> \
  rollback --env dev
```

---

## GitHub Deployments

The **Deploy Staging** workflow creates a GitHub Deployment entry for the `staging` environment.
This allows you to track deployment history and link commits to environment state directly
from pull requests and commit statuses on GitHub.

Deployment states: `in_progress` → `success` | `failure`

---

## Troubleshooting

| Symptom                            | Action                                                                 |
|:-----------------------------------|:-----------------------------------------------------------------------|
| SSM command timed out              | Check EC2 instance health in AWS console. Verify SSM agent is running. |
| Smoke test fails on /healthz       | Check app container status on the EC2 instance via SSM Session Manager.|
| Smoke test fails on /readiness     | App may still be warming up. Wait 30s and retry manually.              |
| Deployment stuck in `in_progress`  | Check GitHub Actions logs. GitHub Deployment status is updated by the workflow steps. |
| Auto-rollback failed               | SSH into the EC2 via SSM Session Manager and inspect Docker logs.      |
