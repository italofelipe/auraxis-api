#!/usr/bin/env python3
"""
Auraxis - Deploy helper (I6) via SSM (no SSH).

Status
- This is a pragmatic stepping stone before full GitHub Actions -> AWS deploy.
- It provides:
  - deploy to DEV/PROD by git ref (branch/tag/commit)
  - basic rollback (deploy previous successfully deployed ref)
  - status (show deployed refs)
  - deterministic execution with SSM + wait-for-success

Why this exists
- We can ship safely without waiting for IAM/OIDC wiring for GitHub Actions.
- We keep infra changes auditable and repeatable.

What it does on the instance
- Locates repo dir in `/opt/auraxis` (preferred) or `/opt/flask_expenses` (legacy).
- Runs `git fetch` and force-checkouts a ref (defaults to `origin/master`).
- Runs preflight checks (repo/env/required keys/docker).
- Applies runtime TLS mode idempotently:
  - uses TLS only when certificate exists
  - auto-requests cert in PROD when possible
  - falls back to HTTP safely without crashing Nginx
- Restarts compose with `docker-compose.prod.yml` (+ optional overlays).
 - Tracks deploy state in `/var/lib/auraxis/deploy_state.json` (per-instance).

Operator prerequisites
- AWS CLI auth working locally.
- EC2 instances are SSM-managed.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"

DEPLOY_STATE_PATH = "/var/lib/auraxis/deploy_state.json"


@dataclass(frozen=True)
class AwsCtx:
    profile: str
    region: str


class AwsCliError(RuntimeError):
    pass


def _run_aws(ctx: AwsCtx, args: list[str], *, expect_json: bool = True) -> Any:
    cmd: list[str] = ["aws"]
    # In CI (GitHub Actions OIDC), we prefer env credentials and may not have a profile.
    if ctx.profile:
        cmd.extend(["--profile", ctx.profile])
    if ctx.region:
        cmd.extend(["--region", ctx.region])
    cmd.extend(args)
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise AwsCliError(
            (p.stderr or "").strip() or f"AWS CLI failed: {' '.join(cmd)}"
        )
    if not expect_json:
        return p.stdout
    stdout = (p.stdout or "").strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _ssm_send_shell(ctx: AwsCtx, instance_id: str, script: str, comment: str) -> str:
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    cmd = (
        "TMP=/tmp/auraxis_ssm_deploy_i6_$$.sh; "
        f"echo '{b64}' | base64 -d > \"$TMP\"; "
        'bash "$TMP"; RC=$?; rm -f "$TMP"; exit $RC'
    )
    payload = json.dumps({"commands": [cmd]})
    out = _run_aws(
        ctx,
        [
            "ssm",
            "send-command",
            "--instance-ids",
            instance_id,
            "--document-name",
            "AWS-RunShellScript",
            "--comment",
            comment,
            "--parameters",
            payload,
        ],
    )
    return str(out["Command"]["CommandId"])


def _wait(ctx: AwsCtx, *, command_id: str, instance_id: str) -> None:
    deadline = time.time() + 1200
    while time.time() < deadline:
        out = _run_aws(
            ctx,
            [
                "ssm",
                "get-command-invocation",
                "--command-id",
                command_id,
                "--instance-id",
                instance_id,
                "--plugin-name",
                "aws:RunShellScript",
            ],
        )
        status = str(out.get("Status") or "Unknown")
        if status in {"Pending", "InProgress", "Delayed"}:
            time.sleep(5)
            continue
        if status != "Success":
            stdout = str(out.get("StandardOutputContent") or "").strip()
            stderr = str(out.get("StandardErrorContent") or "").strip()
            tail_limit = 12000
            raise AwsCliError(
                "Deploy failed. "
                f"instance_id={instance_id} command_id={command_id} status={status}\n"
                f"STDOUT:\n{stdout[-tail_limit:]}\nSTDERR:\n{stderr[-tail_limit:]}"
            )
        return
    raise AwsCliError(
        "Timeout waiting SSM command. "
        f"instance_id={instance_id} command_id={command_id}"
    )


def _build_script(
    *,
    env_name: str,
    aws_region: str,
    git_ref: str | None,
    mode: str,
) -> str:
    domain = "api.auraxis.com.br" if env_name == "prod" else "dev.api.auraxis.com.br"
    cors_origins = (
        "https://www.auraxis.com.br,https://auraxis.com.br,https://app.auraxis.com.br"
        if env_name == "prod"
        else "http://localhost:3000,http://localhost:5173"
    )
    git_ref_setup = f'GIT_REF="{git_ref}"' if git_ref is not None else 'GIT_REF=""'

    return f"""\
set -euo pipefail

MODE="{mode}"
{git_ref_setup}

REPO=""
CANONICAL_REPO=/opt/auraxis
LEGACY_REPO=/opt/flask_expenses
CANONICAL_HAS_REPO="false"
LEGACY_HAS_REPO="false"
if [ -d "$CANONICAL_REPO/.git" ] || [ -f "$CANONICAL_REPO/.git" ]; then
  CANONICAL_HAS_REPO="true"
fi
if [ -d "$LEGACY_REPO/.git" ] || [ -f "$LEGACY_REPO/.git" ]; then
  LEGACY_HAS_REPO="true"
fi

if [ "$CANONICAL_HAS_REPO" = "true" ] && [ "$LEGACY_HAS_REPO" = "true" ]; then
  CANONICAL_REAL="$(readlink -f "$CANONICAL_REPO" || echo "$CANONICAL_REPO")"
  LEGACY_REAL="$(readlink -f "$LEGACY_REPO" || echo "$LEGACY_REPO")"
  if [ "$CANONICAL_REAL" != "$LEGACY_REAL" ]; then
    echo "[i6] repository drift detected between canonical and legacy paths"
    echo "[i6] canonical: $CANONICAL_REPO -> $CANONICAL_REAL"
    echo "[i6] legacy:    $LEGACY_REPO -> $LEGACY_REAL"
    echo "[i6] aborting deploy to avoid updating wrong repository copy"
    exit 16
  fi
  REPO="$CANONICAL_REPO"
elif [ "$CANONICAL_HAS_REPO" = "true" ]; then
  REPO="$CANONICAL_REPO"
  if [ ! -e "$LEGACY_REPO" ]; then
    sudo ln -s "$CANONICAL_REPO" "$LEGACY_REPO"
    echo "[i6] canonicalized legacy path: $LEGACY_REPO -> $CANONICAL_REPO"
  fi
elif [ "$LEGACY_HAS_REPO" = "true" ]; then
  if [ ! -e "$CANONICAL_REPO" ]; then
    sudo ln -s "$LEGACY_REPO" "$CANONICAL_REPO"
    echo "[i6] canonicalized repo path: $CANONICAL_REPO -> $LEGACY_REPO"
  fi
  if [ -d "$CANONICAL_REPO/.git" ] || [ -f "$CANONICAL_REPO/.git" ]; then
    REPO="$CANONICAL_REPO"
  else
    REPO="$LEGACY_REPO"
  fi
fi
if [ -z "$REPO" ]; then
  echo "Repo not found in /opt (expected $CANONICAL_REPO or $LEGACY_REPO)."
  exit 2
fi
cd "$REPO"
echo "[i6] repo=$REPO"

STATE_PATH="{DEPLOY_STATE_PATH}"
sudo mkdir -p "$(dirname "$STATE_PATH")"

OP_USER="ubuntu"
if [ ! -d "/home/$OP_USER" ]; then
  OP_USER="$(id -un)"
fi
sudo -u "$OP_USER" git config --global --add safe.directory "$REPO" || true

CURRENT_REF="$(
  sudo -u "$OP_USER" bash -lc "cd '$REPO' && git rev-parse HEAD" || true
)"
CURRENT_BRANCH="$(
  sudo -u "$OP_USER" bash -lc "cd '$REPO' && git rev-parse --abbrev-ref HEAD" || true
)"

STATE_CURRENT=""
STATE_PREVIOUS=""
if [ -f "$STATE_PATH" ]; then
  STATE_CURRENT="$(python3 - <<'PY' "$STATE_PATH"
import json,sys
p=sys.argv[1]
try:
  data=json.load(open(p,'r',encoding='utf-8'))
  print(data.get('current','') or '')
except Exception:
  print('')
PY
)"
  STATE_PREVIOUS="$(python3 - <<'PY' "$STATE_PATH"
import json,sys
p=sys.argv[1]
try:
  data=json.load(open(p,'r',encoding='utf-8'))
  print(data.get('previous','') or '')
except Exception:
  print('')
PY
)"
fi

if [ "$MODE" = "status" ]; then
  echo "[i6] git: branch=$CURRENT_BRANCH head=$CURRENT_REF"
  echo "[i6] state: current=$STATE_CURRENT previous=$STATE_PREVIOUS path=$STATE_PATH"
  exit 0
fi

if [ "$MODE" = "rollback" ]; then
  if [ -z "$STATE_PREVIOUS" ]; then
    echo "[i6] rollback requested but no previous deploy recorded in $STATE_PATH"
    exit 12
  fi
  GIT_REF="$STATE_PREVIOUS"
fi

if [ -z "$GIT_REF" ]; then
  echo "[i6] missing git ref."
  echo "[i6] Provide --git-ref for deploy or ensure state has previous for rollback."
  exit 13
fi

require_file() {{
  path="$1"
  if [ ! -f "$path" ]; then
    echo "[i6] missing required file: $path"
    exit 21
  fi
}}

require_env_key() {{
  key="$1"
  if ! grep -qE "^${{key}}=" "$ENV_FILE"; then
    echo "[i6] missing required env key in $ENV_FILE: $key"
    exit 22
  fi
}}

require_cmd() {{
  cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[i6] missing command: $cmd"
    exit 23
  fi
}}

ENV_FILE=.env.prod
require_file "$ENV_FILE"
require_file "docker-compose.prod.yml"

require_cmd docker
require_cmd curl
if ! docker info >/dev/null 2>&1; then
  echo "[i6] docker daemon unavailable"
  exit 24
fi

ensure_env_default() {{
  key="$1"
  value="$2"
  if grep -qE "^${{key}}=" "$ENV_FILE"; then
    return 0
  fi
  echo "${{key}}=${{value}}" >> "$ENV_FILE"
  echo "[i6] defaulted $key"
}}

# Backward-compatibility for older .env.prod files on long-lived instances.
ensure_env_default RATE_LIMIT_BACKEND redis
ensure_env_default RATE_LIMIT_REDIS_URL redis://redis:6379/0
ensure_env_default RATE_LIMIT_FAIL_CLOSED true
ensure_env_default LOGIN_GUARD_ENABLED true
ensure_env_default LOGIN_GUARD_BACKEND redis
ensure_env_default LOGIN_GUARD_REDIS_URL redis://redis:6379/0
ensure_env_default LOGIN_GUARD_FAIL_CLOSED true

for key in \\
  SECRET_KEY JWT_SECRET_KEY DOMAIN \\
  POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD \\
  DB_HOST DB_PORT DB_NAME DB_USER DB_PASS \\
  RATE_LIMIT_BACKEND RATE_LIMIT_REDIS_URL RATE_LIMIT_FAIL_CLOSED \\
  LOGIN_GUARD_ENABLED LOGIN_GUARD_BACKEND LOGIN_GUARD_REDIS_URL \\
  LOGIN_GUARD_FAIL_CLOSED; do
  require_env_key "$key"
done

if [ "{env_name}" = "prod" ]; then
  require_env_key CERTBOT_EMAIL
fi

echo "[i6] mode=$MODE git_ref=$GIT_REF"
# Force GitHub SSH traffic over port 443 to avoid environments where port 22
# is blocked (common in hardened VPC egress policies).
GIT_SSH_COMMAND_AURAXIS="ssh -o StrictHostKeyChecking=accept-new \\
  -o ConnectTimeout=15 -o HostName=ssh.github.com -p 443"
echo "[i6] git transport=ssh-over-443"
if [ "$MODE" = "rollback" ]; then
  if ! sudo -u "$OP_USER" bash -lc \\
    "cd '$REPO' && git cat-file -e '$GIT_REF^{{commit}}'"; then
    echo "[i6] rollback ref not available locally: $GIT_REF"
    exit 14
  fi
  sudo -u "$OP_USER" bash -lc \\
    "cd '$REPO' \\
      && git checkout -f '$GIT_REF' \\
      && git reset --hard '$GIT_REF'"
else
  if ! sudo -u "$OP_USER" bash -lc \\
    "cd '$REPO' \\
      && git -c core.sshCommand='$GIT_SSH_COMMAND_AURAXIS' \\
         ls-remote --exit-code origin >/dev/null"; then
    echo "[i6] git remote authentication failed for user: $OP_USER"
    echo "[i6] expected: SSH key configured for git@ssh.github.com:443"
    echo "[i6] fix: configure deploy key for $OP_USER on this instance"
    echo "[i6] and add it to GitHub repo"
    exit 15
  fi
  sudo -u "$OP_USER" bash -lc \\
    "cd '$REPO' \\
      && git -c core.sshCommand='$GIT_SSH_COMMAND_AURAXIS' fetch --all --prune \\
      && git checkout -f '$GIT_REF' \\
      && git reset --hard '$GIT_REF'"
fi

NEW_REF="$(sudo -u "$OP_USER" bash -lc "cd '$REPO' && git rev-parse HEAD")"
echo "[i6] new_head=$NEW_REF"

if [ ! -f "deploy/nginx/default.http.conf" ]; then
  mkdir -p deploy/nginx
  cat > deploy/nginx/default.http.conf <<'CONF'
server {{
    listen 80;
    server_name __DOMAIN__;

    client_max_body_size 10m;
    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}

    location / {{
        proxy_pass http://web:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
    }}
}}
CONF
  echo "[i6] bootstrapped deploy/nginx/default.http.conf"
fi

if [ ! -f "deploy/nginx/default.tls.conf" ]; then
  mkdir -p deploy/nginx
  cat > deploy/nginx/default.tls.conf <<'CONF'
server {{
    listen 80;
    server_name __DOMAIN__;

    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl http2;
    server_name __DOMAIN__;

    ssl_certificate /etc/letsencrypt/live/__DOMAIN__/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/__DOMAIN__/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    client_max_body_size 10m;
    location / {{
        proxy_pass http://web:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
    }}
}}
CONF
  echo "[i6] bootstrapped deploy/nginx/default.tls.conf"
fi

if [ ! -f "deploy/nginx/default.alb.conf" ]; then
  mkdir -p deploy/nginx
  cat > deploy/nginx/default.alb.conf <<'CONF'
server {{
    listen 80;
    server_name __DOMAIN__;

    client_max_body_size 10m;

    location / {{
        proxy_pass http://web:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $http_x_forwarded_port;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header Connection "";
    }}
}}
CONF
  echo "[i6] bootstrapped deploy/nginx/default.alb.conf"
fi

if [ ! -f "deploy/nginx/default.alb_dual.conf" ]; then
  mkdir -p deploy/nginx
  cat > deploy/nginx/default.alb_dual.conf <<'CONF'
server {{
    listen 80;
    server_name __DOMAIN__;

    client_max_body_size 10m;

    location / {{
        proxy_pass http://web:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $http_x_forwarded_port;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
        proxy_set_header Connection "";
    }}
}}

server {{
    listen 443 ssl http2;
    server_name __DOMAIN__;

    ssl_certificate /etc/letsencrypt/live/__DOMAIN__/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/__DOMAIN__/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    client_max_body_size 10m;

    location / {{
        proxy_pass http://web:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
    }}
}}
CONF
  echo "[i6] bootstrapped deploy/nginx/default.alb_dual.conf"
fi

if [ ! -f "scripts/ensure_tls_runtime.sh" ]; then
  mkdir -p scripts
  cat > scripts/ensure_tls_runtime.sh <<'SH'
#!/bin/sh
set -eu
# Idempotent runtime edge switcher for reverse-proxy.
# - EDGE_TLS_MODE=alb:
#   - renders HTTP-only nginx config suitable for ALB TLS termination
#   - skips local certificate issuance entirely
# - EDGE_TLS_MODE=alb_dual:
#   - transitional mode for safe cutover to ALB HTTP origins
#   - requires an existing local certificate
#   - serves HTTP:80 for the new ALB target group while keeping HTTPS:443 alive
# - EDGE_TLS_MODE=instance_tls (default):
#   - if cert exists for DOMAIN: renders TLS nginx config and recreates reverse-proxy
#   - if cert does not exist:
#     - in PROD, optionally requests cert (AUTO_REQUEST_TLS_CERT=true)
#     - falls back to HTTP nginx config without breaking startup
COMPOSE_FILE="${{COMPOSE_FILE:-docker-compose.prod.yml}}"
ENV_FILE="${{ENV_FILE:-.env.prod}}"
ENV_NAME="${{1:-${{AURAXIS_ENV:-prod}}}}"
DOMAIN_INPUT="${{2:-}}"
AUTO_REQUEST_TLS_CERT="${{AUTO_REQUEST_TLS_CERT:-true}}"

read_env_value() {{
  key="$1"
  if [ ! -f "$ENV_FILE" ]; then
    return 0
  fi
  awk -F= -v k="$key" '$1==k {{sub(/^[^=]*=/,""); print; exit}}' "$ENV_FILE"
}}

DOMAIN="${{DOMAIN_INPUT:-${{DOMAIN:-$(read_env_value DOMAIN)}}}}"
CERTBOT_EMAIL="${{CERTBOT_EMAIL:-$(read_env_value CERTBOT_EMAIL)}}"
EDGE_TLS_MODE="${{EDGE_TLS_MODE:-$(read_env_value EDGE_TLS_MODE)}}"
EDGE_TLS_MODE="${{EDGE_TLS_MODE:-instance_tls}}"

cert_exists() {{
  CERT_DIR="/etc/letsencrypt/live/${{DOMAIN}}"
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \\
    run --rm --entrypoint sh certbot \\
    -c "[ -f '${{CERT_DIR}}/fullchain.pem' ] && \\
        [ -f '${{CERT_DIR}}/privkey.pem' ]" >/dev/null
}}

render_http_config() {{
  sed "s/__DOMAIN__/${{DOMAIN}}/g" \\
    deploy/nginx/default.http.conf > deploy/nginx/default.conf
}}

render_tls_config() {{
  sed "s/__DOMAIN__/${{DOMAIN}}/g" \\
    deploy/nginx/default.tls.conf > deploy/nginx/default.conf
}}

render_alb_config() {{
  sed "s/__DOMAIN__/${{DOMAIN}}/g" \\
    deploy/nginx/default.alb.conf > deploy/nginx/default.conf
}}

render_alb_dual_config() {{
  sed "s/__DOMAIN__/${{DOMAIN}}/g" \\
    deploy/nginx/default.alb_dual.conf > deploy/nginx/default.conf
}}

recreate_proxy() {{
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \\
    up -d --force-recreate reverse-proxy
}}

request_certificate() {{
  if [ -z "${{CERTBOT_EMAIL}}" ]; then
    return 1
  fi
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d reverse-proxy
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    --email "${{CERTBOT_EMAIL}}" \
    -d "${{DOMAIN}}" \
    --rsa-key-size 4096 \
    --agree-tos \
    --non-interactive
}}

if [ "${{EDGE_TLS_MODE}}" = "alb" ]; then
  render_alb_config
  recreate_proxy
  exit 0
fi

if [ "${{EDGE_TLS_MODE}}" = "alb_dual" ]; then
  if cert_exists; then
    render_alb_dual_config
    recreate_proxy
    exit 0
  fi
  echo "[tls] EDGE_TLS_MODE=alb_dual requires an existing certificate for ${{DOMAIN}}."
  exit 4
fi

if cert_exists; then
  render_tls_config
  recreate_proxy
  exit 0
fi

if [ "${{ENV_NAME}}" = "prod" ] && [ "${{AUTO_REQUEST_TLS_CERT}}" = "true" ]; then
  if request_certificate && cert_exists; then
    render_tls_config
    recreate_proxy
    exit 0
  fi
fi

render_http_config
recreate_proxy
SH
  chmod +x scripts/ensure_tls_runtime.sh
  echo "[i6] bootstrapped scripts/ensure_tls_runtime.sh"
fi

python3 - "$ENV_FILE" "AURAXIS_ENV" "{env_name}" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); k=sys.argv[2]; v=sys.argv[3]
lines=p.read_text(encoding="utf-8").splitlines()
out=[]; r=False
for line in lines:
    if line.startswith(k+'=') and not r:
        out.append(k+'='+v); r=True
    else:
        out.append(line)
if not r:
    if out and out[-1].strip(): out.append('')
    out.append(k+'='+v)
p.write_text('\\n'.join(out)+'\\n', encoding="utf-8")
PY

python3 - "$ENV_FILE" "AWS_REGION" "{aws_region}" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); k=sys.argv[2]; v=sys.argv[3]
lines=p.read_text(encoding="utf-8").splitlines()
out=[]; r=False
for line in lines:
    if line.startswith(k+'=') and not r:
        out.append(k+'='+v); r=True
    else:
        out.append(line)
if not r:
    if out and out[-1].strip(): out.append('')
    out.append(k+'='+v)
p.write_text('\\n'.join(out)+'\\n', encoding="utf-8")
PY

python3 - "$ENV_FILE" "CORS_ALLOWED_ORIGINS" "{cors_origins}" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]); k=sys.argv[2]; v=sys.argv[3]
lines=p.read_text(encoding="utf-8").splitlines()
out=[]; r=False
for line in lines:
    if line.startswith(k+'=') and not r:
        out.append(k+'='+v); r=True
    else:
        out.append(line)
if not r:
    if out and out[-1].strip(): out.append('')
    out.append(k+'='+v)
p.write_text('\\n'.join(out)+'\\n', encoding="utf-8")
PY

echo "[i6] restarting compose..."
dump_compose_diagnostics() {{
  echo "[i6] dumping compose diagnostics..."
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml ps || true
  WEB_CID="$(
    docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
      ps -q web || true
  )"
  if [ -n "$WEB_CID" ]; then
    echo "[i6] web container id: $WEB_CID"
    docker inspect --format '{{{{json .State}}}}' "$WEB_CID" || true
  fi
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    logs --tail=200 web || true
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    logs --tail=200 reverse-proxy || true
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    logs --tail=120 db || true
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    logs --tail=120 redis || true
}}

if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
  up -d --build --force-recreate db redis web; then
  echo "[i6] compose up failed for db/redis/web"
  dump_compose_diagnostics
  exit 31
fi

WEB_CID="$(
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    ps -q web || true
)"
if [ -z "$WEB_CID" ]; then
  echo "[i6] web container id not found after compose up"
  dump_compose_diagnostics
  exit 32
fi

WEB_HEALTH="starting"
for i in $(seq 1 45); do
  WEB_HEALTH="$(
    docker inspect \\
      --format '{{{{.State.Health.Status}}}}' \\
      "$WEB_CID" 2>/dev/null || echo "unknown"
  )"
  if [ -z "$WEB_HEALTH" ] || [ "$WEB_HEALTH" = "<no value>" ]; then
    WEB_HEALTH="none"
  fi
  if [ "$WEB_HEALTH" = "healthy" ]; then
    echo "[i6] web health=healthy"
    break
  fi
  if [ "$WEB_HEALTH" = "unhealthy" ]; then
    echo "[i6] web health=unhealthy"
    dump_compose_diagnostics
    exit 33
  fi
  sleep 2
done

if [ "$WEB_HEALTH" != "healthy" ]; then
  echo "[i6] web did not become healthy in time (status=$WEB_HEALTH)"
  dump_compose_diagnostics
  exit 34
fi

echo "[i6] ensuring runtime TLS mode..."
AUTO_REQUEST_TLS_CERT="true"
if [ "{env_name}" = "dev" ]; then
  AUTO_REQUEST_TLS_CERT="false"
fi
chmod +x scripts/ensure_tls_runtime.sh
COMPOSE_FILE="docker-compose.prod.yml" ENV_FILE="$ENV_FILE" \\
  AUTO_REQUEST_TLS_CERT="$AUTO_REQUEST_TLS_CERT" \\
  ./scripts/ensure_tls_runtime.sh "{env_name}" "{domain}"

echo "[i6] validating healthz..."
SCHEME="http"
CURL_FLAGS="-fsS"
if grep -q "listen 443" deploy/nginx/default.conf; then
  SCHEME="https"
  CURL_FLAGS="-kfsS"
fi
echo "[i6] edge_scheme=$SCHEME domain={domain}"

for i in $(seq 1 30); do
  WEB_OK="false"
  EDGE_HEALTH_URL="$SCHEME://127.0.0.1/healthz"
  WEB_HEALTH_HOST=127.0.0.1
  WEB_HEALTH_PORT=8000
  WEB_HEALTH_PATH=/healthz
  WEB_HEALTH_URL="http://${{WEB_HEALTH_HOST}}:${{WEB_HEALTH_PORT}}"
  WEB_HEALTH_URL="${{WEB_HEALTH_URL}}${{WEB_HEALTH_PATH}}"
  if docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    exec -T web python - "$WEB_HEALTH_URL" >/dev/null 2>&1 <<'PY'
import sys
import urllib.request

urllib.request.urlopen(sys.argv[1], timeout=3)
PY
  then
    WEB_OK="true"
  fi

  if [ "$WEB_OK" = "true" ] \\
    && curl $CURL_FLAGS "$EDGE_HEALTH_URL" -H "Host: {domain}" >/dev/null; then
    echo "[i6] OK"
    python3 - <<'PY' "$STATE_PATH" "$CURRENT_REF" "$NEW_REF"
import json,sys
path=sys.argv[1]
prev=sys.argv[2] or ""
cur=sys.argv[3] or ""
data={{"previous": prev, "current": cur}}
with open(path,"w",encoding="utf-8") as f:
  json.dump(data,f,indent=2,sort_keys=True)
print("[i6] wrote deploy state:", path, data)
PY
    exit 0
  fi
  sleep 2
done
echo "[i6] healthz validation failed"
echo "[i6] dumping compose diagnostics..."
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml ps || true
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
  logs --tail=120 web || true
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
  logs --tail=120 reverse-proxy || true
exit 5
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis deploy helper (I6) via SSM")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)

    sub = p.add_subparsers(dest="cmd", required=True)
    p_deploy = sub.add_parser("deploy", help="Deploy a git ref to DEV/PROD.")
    p_deploy.add_argument("--env", choices=["dev", "prod"], required=True)
    p_deploy.add_argument("--git-ref", default="origin/master")
    p_rb = sub.add_parser(
        "rollback",
        help="Rollback DEV/PROD to the previous successfully deployed ref.",
    )
    p_rb.add_argument("--env", choices=["dev", "prod"], required=True)
    p_status = sub.add_parser("status", help="Show deploy state and current git ref.")
    p_status.add_argument("--env", choices=["dev", "prod"], required=True)
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)

    if args.cmd in {"deploy", "rollback", "status"}:
        env_name = str(args.env)
        instance_id = (
            args.dev_instance_id if env_name == "dev" else args.prod_instance_id
        )

        mode = str(args.cmd)
        git_ref: str | None = None
        comment_ref = ""
        if mode == "deploy":
            git_ref = str(args.git_ref)
            comment_ref = f" ref={git_ref}"

        script = _build_script(
            env_name=env_name,
            aws_region=ctx.region,
            git_ref=git_ref,
            mode=mode,
        )
        cmd_id = _ssm_send_shell(
            ctx,
            instance_id,
            script,
            f"auraxis: i6 {mode} ({env_name}){comment_ref}",
        )
        print(f"{env_name.upper()} command_id={cmd_id}")
        _wait(ctx, command_id=cmd_id, instance_id=instance_id)
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
