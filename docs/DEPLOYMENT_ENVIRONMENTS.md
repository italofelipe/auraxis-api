# Deployment Environments (DEV and PROD)

Updated at: 2026-02-10

## Goal
Establish explicit local/staging runtime profiles for development and production, keeping backward compatibility and reducing deployment risks.

## Files introduced
- `docker-compose.dev.yml`: local development stack.
- `docker-compose.prod.yml`: production-like stack.
- `Dockerfile.prod`: production image with gunicorn.
- `scripts/entrypoint_prod.sh`: startup orchestration (db wait + migrations + gunicorn).
- `deploy/nginx/default.conf`: reverse proxy to Flask app.
- `.env.dev.example`: development environment variables template.
- `.env.prod.example`: production environment variables template.

## DEV profile
- Uses `docker-compose.dev.yml`.
- Uses `.env.dev` through `env_file`.
- `AUTO_CREATE_DB=true` to keep local onboarding simple.
- Runs Flask development server (`flask run`).
- Exposes app on `localhost:3333`.

### Commands
```bash
cp .env.dev.example .env.dev
docker compose -f docker-compose.dev.yml up --build
```

## PROD profile
- Uses `docker-compose.prod.yml`.
- Uses `.env.prod` through `env_file`.
- `AUTO_CREATE_DB=false` and migrations via `flask db upgrade` on startup.
- Startup fails if `migrations/` is missing (unless `ALLOW_SCHEMA_BOOTSTRAP_WITHOUT_MIGRATIONS=true` is explicitly set for controlled recovery).
- Runs Gunicorn behind Nginx.
- Exposes app on `localhost:80`.
- Supports TLS with Certbot + Nginx (`443`) using shared challenge/certificate volumes.
- Supports an ALB edge mode with TLS termination in ACM/ALB and HTTP-only origin on the instance (`EDGE_TLS_MODE=alb`).
- Supports a transitional dual-edge mode for safe origin cutover (`EDGE_TLS_MODE=alb_dual`).

### Commands
```bash
cp .env.prod.example .env.prod
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml logs -f
docker compose -f docker-compose.prod.yml down
```

### TLS enablement (AWS/domain)
```bash
./scripts/request_tls_cert.sh
cp deploy/nginx/default.tls.conf deploy/nginx/default.conf
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate reverse-proxy
```

### ALB edge mode
Use when TLS terminates on an AWS Application Load Balancer instead of on the host:

```bash
echo 'EDGE_TLS_MODE=alb' >> .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate reverse-proxy
```

Operational expectations:
- ACM certificate is attached to the ALB listener
- target group forwards HTTP to the instance
- Route 53 points `api.auraxis.com.br` to the ALB
- host-level Certbot is no longer part of the public edge for that domain

### ALB transitional cutover mode
Use when moving a live environment from `HTTPS origin` to `HTTP origin` behind the ALB:

```bash
echo 'EDGE_TLS_MODE=alb_dual' >> .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate reverse-proxy
```

Operational expectations:
- requires an existing local certificate on the host
- keeps `443` alive for the current ALB target group
- exposes `80` at the same time so the new HTTP target group can warm up
- after the ALB listener cutover is stable, switch the host from `alb_dual` to `alb`

Detailed runbook:
- `docs/RUNBOOK.md`

## Compatibility note
- `app/__init__.py` now gates `db.create_all()` using `AUTO_CREATE_DB`.
- Default is `false` to avoid implicit schema drift.
- Production compose explicitly sets `AUTO_CREATE_DB=false`.

## Security note
- Never commit `.env.dev`/`.env.prod` with real secrets.
- Prefer GitHub Actions secrets + runtime environment configuration for CI/CD and production.
- For cloud runtime, prefer AWS SSM/Secrets Manager as source of truth and generate `.env.runtime`:
```bash
python3 scripts/sync_cloud_secrets.py --backend ssm --ssm-path /auraxis/prod --output .env.runtime
docker compose --env-file .env.runtime -f docker-compose.prod.yml up -d --build
```

For host replacement and other operational recovery flows, we also support
materializing a complete `.env.prod` from the example template plus cloud
secrets:

```bash
python3 scripts/sync_cloud_secrets.py \
  --backend ssm \
  --region us-east-1 \
  --ssm-path /auraxis/dev \
  --base-env .env.prod.example \
  --output .env.prod \
  --set AURAXIS_ENV=dev \
  --set DOMAIN=dev.api.auraxis.com.br \
  --set EDGE_TLS_MODE=instance_tls
```

This keeps AWS as the source of truth for sensitive keys while making host
bootstrap reproducible for Docker Compose.

Runbook:
- `docs/CLOUD_SECRETS_RUNBOOK.md`
- `docs/AWS_COST_GUARDRAILS.md`
- `docs/RDS_PLAN_B.md`
