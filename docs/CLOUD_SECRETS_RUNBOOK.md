# Cloud Secrets Runbook (SSM / Secrets Manager)

Updated at: 2026-02-11

## Goal
Use AWS as source of truth for runtime secrets in cloud environments (DEV/PROD), avoiding `.env` as primary secret store.

## Script
- `/opt/auraxis/scripts/sync_cloud_secrets.py`

This script fetches secrets from:
- AWS SSM Parameter Store (`--backend ssm`), or
- AWS Secrets Manager (`--backend secretsmanager`)

and generates an env file for Docker Compose (default: `.env.runtime`).
It can also merge cloud secrets with a base env template via `--base-env` and
explicit overrides via `--set KEY=VALUE`.

## Recommended model
1. Keep `.env.prod` / `.env.dev` with non-sensitive config defaults only.
2. Store sensitive keys in AWS:
   - `SECRET_KEY`, `JWT_SECRET_KEY`
   - `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`
   - `POSTGRES_PASSWORD` (when applicable)
   - integration tokens (e.g., `BRAPI_KEY`)
3. Before startup, generate runtime env from AWS and use it in Compose.

## SSM example
Expected parameter naming:
- `/auraxis/prod/SECRET_KEY`
- `/auraxis/prod/JWT_SECRET_KEY`
- `/auraxis/prod/DB_HOST`
- ...

Command:
```bash
python3 scripts/sync_cloud_secrets.py \
  --backend ssm \
  --region us-east-1 \
  --ssm-path /auraxis/prod \
  --output .env.runtime
```

## Secrets Manager example
Create one secret JSON object:
```json
{
  "SECRET_KEY": "...",
  "JWT_SECRET_KEY": "...",
  "DB_HOST": "db",
  "DB_PORT": "5432"
}
```

Command:
```bash
python3 scripts/sync_cloud_secrets.py \
  --backend secretsmanager \
  --region us-east-1 \
  --secret-id auraxis/prod/app \
  --output .env.runtime
```

## Startup with runtime env
```bash
docker compose --env-file .env.runtime -f docker-compose.prod.yml up -d --build
```

## Materialize `.env.prod` from template + cloud secrets

Useful for host replacement/bootstrap flows where Docker Compose still expects
`.env.prod` on disk:

```bash
python3 scripts/sync_cloud_secrets.py \
  --backend ssm \
  --region us-east-1 \
  --ssm-path /auraxis/dev \
  --base-env .env.prod.example \
  --output .env.prod \
  --set AURAXIS_ENV=dev \
  --set AURAXIS_SSM_PATH=/auraxis/dev \
  --set DOMAIN=dev.api.auraxis.com.br \
  --set EDGE_TLS_MODE=instance_tls
```

## Rotation process (baseline)
1. Rotate secret in AWS (new value).
2. Re-run `sync_cloud_secrets.py` to refresh `.env.runtime`.
3. Restart stack:
```bash
docker compose --env-file .env.runtime -f docker-compose.prod.yml up -d
```
4. Validate health:
```bash
curl -I https://api.auraxis.com.br/docs/
```

## Security notes
- `.env.runtime` is generated with permission `600`.
- Never commit `.env.runtime`.
- Use least-privilege IAM permissions for EC2 role:
  - `ssm:GetParametersByPath` (if SSM),
  - `secretsmanager:GetSecretValue` (if Secrets Manager),
  - `kms:Decrypt` when applicable.
