# Disaster Recovery Runbook — Auraxis API

> **Audience:** On-call engineer / platform owner
> **Last updated:** 2026-04-05
> **Infra reference:** `.context/09_infra_map.md` (canonical AWS resource map)

---

## Severity Levels

| Level | Definition | Response time |
|:------|:-----------|:--------------|
| **SEV-1** | Complete API outage — `https://api.auraxis.com.br` unreachable or returning 5xx for all requests | Immediate (< 15 min) |
| **SEV-2** | Partial degradation — specific endpoints failing, database corruption detected, data loss risk | < 1 hour |
| **SEV-3** | Bad deploy — regression in behaviour, elevated error rate in Sentry, no data loss | < 4 hours |

---

## RTO / RPO Targets

| Target | Value | Rationale |
|:-------|:------|:----------|
| **RTO** (Recovery Time Objective) | 4 hours | Single-person on-call; no SLA commitments in MVP phase |
| **RPO** (Recovery Point Objective) | 24 hours | Daily S3 backup at 03:00 UTC via `scripts/backup-db-to-s3.sh` |

> EBS snapshots via AWS Backup provide a secondary recovery point. Check AWS Console
> → AWS Backup → Recovery Points for the most recent snapshot of `vol-07f0258e289bc680f`.

---

## Pre-flight: Verify Backup Before Any Restore

Always verify the target backup before starting a restore:

```bash
# Verify most recent backup
bash scripts/verify-backup.sh

# Verify a specific date
BACKUP_DATE=2026-04-04 bash scripts/verify-backup.sh
```

Exit code `0` = backup is valid and safe to restore.
Exit code `1` = backup missing or corrupt — escalate and check prior dates.

---

## Scenario 1: EC2 Instance Failure (SEV-1)

**Symptoms:** `https://api.auraxis.com.br` is unreachable. EC2 console shows the instance
`i-0057e3b52162f78f8` is stopped, terminated, or in a failed state.

### Step 1 — Assess

```bash
aws ec2 describe-instance-status \
  --instance-ids i-0057e3b52162f78f8 \
  --region us-east-1 \
  --output table
```

If the instance is unrecoverable (terminated, hardware fault), proceed to Step 2.

### Step 2 — Launch replacement instance

Use the dev recovery script as template (it encodes the exact configuration):

```bash
./scripts/python_exec.sh scripts/aws_dev_recovery_i17.py \
  --profile auraxis-admin \
  --region us-east-1 \
  replace \
  --git-ref origin/master
```

> **Note:** `aws_dev_recovery_i17.py` was built for the dev instance but documents
> the exact AMI, subnet, security group (`sg-0edf5ab745a438dd2`), and IAM profile
> needed. For prod, substitute the prod EIP `100.49.10.188` in step 4.

Alternatively, launch a new t2.micro in `us-east-1` manually:
- AMI: Ubuntu 24.04 LTS (same as existing instances)
- Instance type: `t2.micro`
- Security group: `sg-0edf5ab745a438dd2` (ports 80, 443, 22-restricted)
- IAM instance profile: same profile as `i-0057e3b52162f78f8`
- EBS: 20 GB gp3 root volume

### Step 3 — Bootstrap the new instance

Connect via SSM Session Manager (no SSH required):

```bash
aws ssm start-session \
  --target <new-instance-id> \
  --region us-east-1 \
  --profile auraxis-admin
```

Inside the session:

```bash
# Install Docker + Compose v2
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-plugin git

# Add swap (required for Docker builds on t2.micro)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Clone repo
sudo git clone https://github.com/italofelipe/auraxis-api.git /opt/auraxis
```

### Step 4 — Restore database from S3

```bash
# Copy .env.prod from SSM Parameter Store or a secure location
sudo bash /opt/auraxis/scripts/restore-db-from-s3.sh
```

See `scripts/restore-db-from-s3.sh` for full usage. The script:
1. Prompts for confirmation (type `RESTORE` to proceed)
2. Downloads the backup from `s3://auraxis-db-backups/daily/<date>.sql.gz`
3. Drops and recreates the database
4. Restores the SQL dump

### Step 5 — Start the application

```bash
cd /opt/auraxis
sudo docker compose -f docker-compose.prod.yml up -d
```

### Step 6 — Reassociate the Elastic IP

```bash
# Get allocation ID for EIP 100.49.10.188
aws ec2 describe-addresses \
  --filters "Name=public-ip,Values=100.49.10.188" \
  --region us-east-1 \
  --query 'Addresses[0].AllocationId' \
  --output text

# Associate with new instance
aws ec2 associate-address \
  --instance-id <new-instance-id> \
  --allocation-id <allocation-id> \
  --region us-east-1 \
  --profile auraxis-admin
```

### Step 7 — Validate

See the [Verification Checklist](#verification-checklist-after-any-restore) below.

---

## Scenario 2: Database Corruption (SEV-2)

**Symptoms:** API returning `500` errors related to data queries, `psql` showing
corrupted tables, `pg_dump` failing with integrity errors.

### Step 1 — Isolate

Stop the application container to prevent further writes:

```bash
# Via SSM on the EC2 instance
cd /opt/auraxis
sudo docker compose -f docker-compose.prod.yml stop web
```

### Step 2 — Verify most recent valid backup

```bash
bash scripts/verify-backup.sh
```

If the most recent backup is corrupt, check previous dates:

```bash
aws s3 ls s3://auraxis-db-backups/daily/ | sort -r | head -10
# Pick a known-good date
BACKUP_DATE=2026-04-03 bash scripts/verify-backup.sh
```

### Step 3 — Restore from S3

```bash
# Restore a specific date
bash scripts/restore-db-from-s3.sh 2026-04-03
```

The restore script handles: download, DB drop+recreate, SQL restore, and app restart.

### Step 4 — Alternative: Restore from EBS Snapshot

If S3 backups are unavailable or you need a more granular recovery point:

1. Find the latest EBS snapshot in AWS Console → EC2 → Snapshots
   - Filter by volume `vol-07f0258e289bc680f`
2. Create a new EBS volume from the snapshot (same AZ as `i-0057e3b52162f78f8`)
3. Stop the EC2 instance, detach the corrupted volume, attach the restored volume as `/dev/xvda`
4. Start the instance

> EBS snapshot recovery replaces the entire instance disk — use only when S3 restore
> is not viable (e.g., backup bucket unavailable).

### Step 5 — Run pending migrations

After restoring an older backup, apply any missing Alembic migrations:

```bash
# Via SSM on the EC2 instance
cd /opt/auraxis
sudo docker compose -f docker-compose.prod.yml exec web flask db upgrade
```

### Step 6 — Validate

See the [Verification Checklist](#verification-checklist-after-any-restore) below.

---

## Scenario 3: Bad Deploy Rollback (SEV-3)

**Symptoms:** Sentry error spike after a deploy, health check returning non-200,
smoke tests failing, regression in API behaviour.

### Step 1 — Identify the bad deploy

Check Sentry for the spike timestamp:
- Dashboard: https://sentry.io → Auraxis API project → Issues (sorted by First Seen)

Check deploy history on the EC2 instance:

```bash
# Via SSM
cat /var/lib/auraxis/deploy_state.json
```

This file contains `current_ref` and `previous_ref`.

### Step 2 — Rollback via deploy script (recommended)

```bash
./scripts/python_exec.sh scripts/aws_deploy_i6.py \
  --profile auraxis-admin \
  --region us-east-1 \
  rollback \
  --env prod
```

The script redeploys the `previous_ref` stored in `/var/lib/auraxis/deploy_state.json`
without requiring a new `git fetch`.

### Step 3 — Alternative: git revert on master + re-deploy

If the rollback script is not usable (e.g., state file corrupted):

```bash
# Locally, identify the bad commit
git -C repos/auraxis-api log --oneline -10

# Revert (creates a new commit — does not rewrite history)
git -C repos/auraxis-api revert <bad-commit-sha> --no-edit
git -C repos/auraxis-api push origin master

# Trigger a deploy via GitHub Actions or manually:
./scripts/python_exec.sh scripts/aws_deploy_i6.py \
  --profile auraxis-admin \
  --region us-east-1 \
  deploy \
  --env prod \
  --git-ref origin/master
```

> Never use `git reset --hard` + force-push on `master`. Always use `git revert`
> to preserve history (per `.context/07_steering_global.md` — no history rewrite).

### Step 4 — Validate

See the [Verification Checklist](#verification-checklist-after-any-restore) below.

---

## Verification Checklist After Any Restore

Run these checks after completing any recovery scenario:

- [ ] Health endpoint returns `200`:
  ```bash
  curl -fsS https://api.auraxis.com.br/healthz
  ```
- [ ] GraphQL smoke check returns expected validation error (not 500):
  ```bash
  curl -s -X POST https://api.auraxis.com.br/graphql \
    -H "Content-Type: application/json" \
    -d '{"query":""}' | python3 -m json.tool
  ```
- [ ] Authentication endpoint rejects invalid credentials with 401 (not 500):
  ```bash
  curl -s -X POST https://api.auraxis.com.br/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"test@test.com","password":"wrong"}' | python3 -m json.tool
  ```
- [ ] Database tables are accessible:
  ```bash
  # Via SSM on EC2
  docker exec auraxis-db-1 psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c '\dt'
  ```
- [ ] Pending migrations applied:
  ```bash
  docker compose -f docker-compose.prod.yml exec web flask db current
  docker compose -f docker-compose.prod.yml exec web flask db upgrade
  ```
- [ ] No critical errors in Sentry for 5 minutes after restore
- [ ] S3 backup verification passes:
  ```bash
  bash scripts/verify-backup.sh
  ```

---

## Related Resources

| Resource | Path / URL |
|:---------|:-----------|
| S3 backup script | `scripts/backup-db-to-s3.sh` |
| S3 restore script | `scripts/restore-db-from-s3.sh` |
| Backup verification | `scripts/verify-backup.sh` |
| API rollback procedure | `docs/runbooks/api-rollback.md` |
| AWS infra map | `.context/09_infra_map.md` |
| General operational runbook | `docs/RUNBOOK.md` |
| Dev instance recovery script | `scripts/aws_dev_recovery_i17.py` |
| Deploy script | `scripts/aws_deploy_i6.py` |
