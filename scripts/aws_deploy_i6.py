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
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"

DEPLOY_STATE_PATH = "/var/lib/auraxis/deploy_state.json"

# Bump this when the on-disk shape of deploy_state.json changes. Older state
# files (no schema_version key) trigger a warning on read so operators know to
# repair them. See issue #1253.
DEPLOY_STATE_SCHEMA_VERSION = 2

# Canonical GHCR image URI pattern. Used in two places:
#  - Python validator (is_valid_ghcr_image_uri) for unit-testable behavior.
#  - Bash regex inside the SSM script for in-instance rollback validation.
# Both must agree; tests pin the shape via GHCR_IMAGE_URI_PATTERN. The pattern
# is intentionally minimal (matches the AC in issue #1253) so it works under
# both Python ``re`` and POSIX ERE (``grep -E``) without character-class
# portability issues.
GHCR_IMAGE_URI_PATTERN = r"^ghcr\.io/.+:.+$"
# Stricter pure-Python check used by ``is_valid_ghcr_image_uri``: forbids
# whitespace inside the path/tag, which the bash regex also rejects (the
# rollback validator pipes the value through ``printf '%s'`` and ``grep -Eq``,
# and any embedded newline would already break the bash branch).
_GHCR_IMAGE_URI_RE = re.compile(r"^ghcr\.io/[^:\s]+:[^\s]+$")


def is_valid_ghcr_image_uri(value: Any) -> bool:
    """Return True iff ``value`` looks like a canonical GHCR image URI.

    Accepts: ``ghcr.io/<owner>/<repo>:<tag>`` (tag = git SHA, semver, etc.).
    Rejects: bare git SHAs, Docker Hub references, empty/whitespace, non-strings.

    This is the validator used in the rollback path of ``aws_deploy_i6.py`` to
    catch legacy state files (issue #1253) where ``previous`` was stored as a
    bare 40-char git SHA — which ``docker pull`` then interprets as Docker Hub
    and refuses with an opaque "access denied" error.
    """
    if not isinstance(value, str):
        return False
    if not value.strip():
        return False
    return _GHCR_IMAGE_URI_RE.match(value) is not None


@dataclass(frozen=True)
class AwsCtx:
    profile: str
    region: str


class AwsCliError(RuntimeError):
    pass


class SsmCommandFailed(AwsCliError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__(_format_failure_message(report))


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


def _truncate_output(value: str, *, limit: int = 12000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def _extract_invocation_report(
    invocation: dict[str, Any], *, instance_id: str, command_id: str
) -> dict[str, Any]:
    stdout = str(invocation.get("StandardOutputContent") or "").strip()
    stderr = str(invocation.get("StandardErrorContent") or "").strip()
    return {
        "instance_id": instance_id,
        "command_id": command_id,
        "status": str(invocation.get("Status") or "Unknown"),
        "status_details": str(invocation.get("StatusDetails") or ""),
        "response_code": invocation.get("ResponseCode"),
        "execution_start_date_time": str(
            invocation.get("ExecutionStartDateTime") or ""
        ),
        "execution_end_date_time": str(invocation.get("ExecutionEndDateTime") or ""),
        "standard_output_url": str(invocation.get("StandardOutputUrl") or ""),
        "standard_error_url": str(invocation.get("StandardErrorUrl") or ""),
        "stdout_tail": _truncate_output(stdout),
        "stderr_tail": _truncate_output(stderr),
    }


def _format_failure_message(report: dict[str, Any]) -> str:
    return (
        "Deploy failed. "
        f"instance_id={report['instance_id']} "
        f"command_id={report['command_id']} "
        f"status={report['status']} "
        f"status_details={report['status_details'] or '<none>'} "
        f"response_code={report['response_code']}\n"
        f"STDOUT:\n{report['stdout_tail']}\n"
        f"STDERR:\n{report['stderr_tail']}"
    )


def _write_diagnostics_json(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_github_summary(report: dict[str, Any]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    status = str(report.get("status") or "Unknown")
    icon = "✅" if status == "Success" else "❌"
    lines = [
        f"### {icon} Deploy via SSM diagnostics",
        "",
        f"- Environment: `{report.get('environment', '')}`",
        f"- Mode: `{report.get('mode', '')}`",
        f"- Git ref: `{report.get('git_ref') or '<n/a>'}`",
        f"- Instance ID: `{report.get('instance_id', '')}`",
        f"- Command ID: `{report.get('command_id', '')}`",
        f"- Status: `{status}`",
        f"- Status details: `{report.get('status_details') or '<none>'}`",
        f"- Response code: `{report.get('response_code')}`",
    ]

    stdout_tail = str(report.get("stdout_tail") or "")
    stderr_tail = str(report.get("stderr_tail") or "")
    if stdout_tail:
        lines.extend(["", "#### STDOUT tail", "", "```text", stdout_tail, "```"])
    if stderr_tail:
        lines.extend(["", "#### STDERR tail", "", "```text", stderr_tail, "```"])

    with open(summary_path, "a", encoding="utf-8") as summary_file:
        summary_file.write("\n".join(lines) + "\n")


def _build_generic_report(
    *,
    env_name: str,
    mode: str,
    git_ref: str | None,
    instance_id: str,
    command_id: str | None,
    error: str,
) -> dict[str, Any]:
    return {
        "environment": env_name,
        "mode": mode,
        "git_ref": git_ref or "",
        "instance_id": instance_id,
        "command_id": command_id or "",
        "status": "ClientError",
        "status_details": error,
        "response_code": None,
        "execution_start_date_time": "",
        "execution_end_date_time": "",
        "standard_output_url": "",
        "standard_error_url": "",
        "stdout_tail": "",
        "stderr_tail": error,
    }


def _record_diagnostics(
    *,
    diagnostics_json_path: str | None,
    report: dict[str, Any],
) -> None:
    if diagnostics_json_path:
        _write_diagnostics_json(diagnostics_json_path, report)
    _append_github_summary(report)


def _wait(ctx: AwsCtx, *, command_id: str, instance_id: str) -> dict[str, Any]:
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
            raise SsmCommandFailed(
                _extract_invocation_report(
                    out, instance_id=instance_id, command_id=command_id
                )
            )
        return dict(out)
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
    web_image: str = "",
    ghcr_token: str = "",
) -> str:
    domain = "api.auraxis.com.br" if env_name == "prod" else "dev.api.auraxis.com.br"
    cors_origins = (
        "https://www.auraxis.com.br,https://auraxis.com.br,https://app.auraxis.com.br"
        if env_name == "prod"
        else "http://localhost:3000,http://localhost:5173"
    )
    git_ref_setup = f'GIT_REF="{git_ref}"' if git_ref is not None else 'GIT_REF=""'
    web_image_setup = f'WEB_IMAGE="{web_image}"'
    ghcr_token_setup = f'GHCR_TOKEN="{ghcr_token}"'
    ghcr_pattern = GHCR_IMAGE_URI_PATTERN
    schema_version = DEPLOY_STATE_SCHEMA_VERSION

    return f"""\
set -euo pipefail

MODE="{mode}"
{git_ref_setup}
{web_image_setup}
{ghcr_token_setup}

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
STATE_SCHEMA_VERSION=""
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
  STATE_SCHEMA_VERSION="$(python3 - <<'PY' "$STATE_PATH"
import json,sys
p=sys.argv[1]
try:
  data=json.load(open(p,'r',encoding='utf-8'))
  v=data.get('schema_version','')
  print(v if v == '' else str(v))
except Exception:
  print('')
PY
)"
  if [ -z "$STATE_SCHEMA_VERSION" ]; then
    echo "[i6] WARNING: deploy_state.json missing 'schema_version'; \
treating as legacy v1 — will be upgraded to v{schema_version} on next \
successful deploy."
  fi
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
  # Defensive: 'previous' must be a fully-qualified GHCR image URI. Legacy
  # state files (pre-#1253) stored bare 40-char git SHAs here, which docker
  # pull then interpreted as Docker Hub references and rejected with an
  # opaque "access denied" error. Fail fast with an actionable message so
  # on-call can repair $STATE_PATH instead of chasing a docker auth red
  # herring.
  if ! printf '%s' "$STATE_PREVIOUS" \\
       | grep -Eq '{ghcr_pattern}'; then
    echo "[i6] rollback aborted: previous='$STATE_PREVIOUS' is not a valid \
GHCR image URI (expected 'ghcr.io/<owner>/<repo>:<tag>')."
    echo "[i6] inspect $STATE_PATH and repair the 'previous' field (or clear \
it to fail-fast on the next rollback)."
    exit 14
  fi
  # Rollback uses the previously deployed image URI from state — not a git ref.
  WEB_IMAGE="$STATE_PREVIOUS"
  echo "[i6] rollback: target image=$WEB_IMAGE"
fi

if [ "$MODE" = "deploy" ] && [ -z "$WEB_IMAGE" ]; then
  echo "[i6] missing --image (WEB_IMAGE). Pass the GHCR image URI to deploy." >&2
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

# Pre-flight: disk check. docker pull needs ~1GB buffer; no build = no large cache needed.
DISK_FREE_GB=$(df / --output=avail -BG | tail -1 | tr -d 'G ')
echo "[i6] disk: ${{DISK_FREE_GB}}GB free"
if [ "${{DISK_FREE_GB}}" -lt 2 ]; then
  echo "[i6] disk < 2GB — pruning stopped containers and dangling images..."
  docker system prune -f >/dev/null 2>&1 || true
  DISK_FREE_GB=$(df / --output=avail -BG | tail -1 | tr -d 'G ')
  echo "[i6] disk after prune: ${{DISK_FREE_GB}}GB free"
fi
if [ "${{DISK_FREE_GB}}" -lt 1 ]; then
  echo "[i6] ABORT: only ${{DISK_FREE_GB}}GB free — need at least 1GB for docker pull."
  echo "[i6] Fix: docker system prune -af --volumes on the instance."
  exit 25
fi
echo "[i6] disk OK: ${{DISK_FREE_GB}}GB free"

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

echo "[i6] mode=$MODE git_ref=$GIT_REF image=$WEB_IMAGE"
# Force GitHub SSH traffic over port 443 to avoid environments where port 22
# is blocked (common in hardened VPC egress policies).
GIT_SSH_COMMAND_AURAXIS="ssh -o StrictHostKeyChecking=accept-new \\
  -o ConnectTimeout=15 -o HostName=ssh.github.com -p 443"
echo "[i6] git transport=ssh-over-443"
# Fetch + checkout to sync compose files and nginx configs.
# Application code now lives in the Docker image (GHCR) — git is config-only.
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
SYNC_REF="${{GIT_REF:-origin/master}}"
# Normalize a bare branch name (e.g. "master") to its remote-tracking ref
# ("origin/master"). `git fetch` advances origin/<branch> but NOT the local
# <branch>, so `git reset --hard <local-branch>` can land on a stale commit.
# Root cause of the exit-36 deploys (2026-06-03): the host's local `master` was
# 481 commits behind, so the reset restored an ancient docker-compose.prod.yml
# pinning `image: auraxis-web` (a local build without recent migrations) instead
# of `${{WEB_IMAGE:-ghcr...}}` — the migration step then hit "Can't locate
# revision". A sha or tag is used as-is.
case "$SYNC_REF" in
  origin/* | refs/* | HEAD) : ;;
  *)
    if sudo -u "$OP_USER" bash -lc \\
      "cd '$REPO' && git show-ref --verify -q 'refs/remotes/origin/$SYNC_REF'"
    then
      echo "[i6] normalizing branch ref '$SYNC_REF' -> 'origin/$SYNC_REF'"
      SYNC_REF="origin/$SYNC_REF"
    fi
    ;;
esac
sudo -u "$OP_USER" bash -lc \\
  "cd '$REPO' \\
    && git -c core.sshCommand='$GIT_SSH_COMMAND_AURAXIS' fetch --all --prune \\
    && git checkout -f '$SYNC_REF' \\
    && git reset --hard '$SYNC_REF'"

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

echo "[i6] rolling deploy: web-only restart (db/redis preserved)..."
dump_compose_diagnostics() {{
  echo "[i6] dumping compose diagnostics..."
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml ps || true
  WEB_CID="$(
    docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
      ps -q web | head -n1 || true
  )"
  if [ -n "$WEB_CID" ]; then
    echo "[i6] web container id: $WEB_CID"
    docker inspect --format '{{{{json .State}}}}' "$WEB_CID" || true
  fi
  # web logs are the most useful for a failed migration; keep them. Cap the
  # reverse-proxy access log to a few lines — at --tail=200 it floods the SSM
  # 24KB output window and pushes the real alembic error out of the captured
  # tail (root cause of the unreadable exit-36 deploys, 2026-06-03).
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    logs --tail=120 web || true
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    logs --tail=15 reverse-proxy || true
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    logs --tail=40 db || true
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    logs --tail=20 redis || true
}}

# Phase 1: Ensure infrastructure services are up (never force-recreate if healthy).
# Restarting db/redis during a web-only deploy drops in-flight DB connections
# and increases risk unnecessarily — keep them alive across deploys.
# Only start services that are actually defined in the compose file — db may be
# commented out when using RDS or a managed postgres host.
echo "[i6] ensuring infrastructure services (db, redis)..."
_INFRA_UP=""
for _svc in db redis; do
  if docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
      config --services 2>/dev/null | grep -qx "${{_svc}}"; then
    _INFRA_UP="${{_INFRA_UP}} ${{_svc}}"
  fi
done
_INFRA_UP="${{_INFRA_UP# }}"
if [ -n "${{_INFRA_UP}}" ]; then
  if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    up -d --no-recreate ${{_INFRA_UP}}; then
    echo "[i6] failed to start infrastructure services: ${{_INFRA_UP}}"
    dump_compose_diagnostics
    exit 30
  fi
  echo "[i6] infrastructure services started: ${{_INFRA_UP}}"
else
  echo "[i6] no local db/redis services in compose (RDS/managed-cache mode) — skipping Phase 1."
fi

# Phase 2: Wait for db to accept connections before starting web.
# Migrations (MIGRATE_ON_START=true) run inside the web container on startup
# and require a live PostgreSQL connection.
echo "[i6] waiting for db readiness (max 60s)..."
for i in $(seq 1 20); do
  DB_CID="$(docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml ps -q db 2>/dev/null || true)"
  if [ -n "$DB_CID" ]; then
    DB_HEALTH="$(docker inspect --format '{{{{.State.Health.Status}}}}' "$DB_CID" 2>/dev/null || echo "none")"
    if [ "$DB_HEALTH" = "healthy" ] || [ "$DB_HEALTH" = "none" ]; then
      echo "[i6] db ready (health=$DB_HEALTH)"
      break
    fi
    echo "[i6] db not ready yet (health=$DB_HEALTH), attempt $i/20..."
  fi
  sleep 3
done

# Phase 3: Pull pre-built image from GHCR (built in GitHub Actions — no local build).
if [ -n "$GHCR_TOKEN" ]; then
  echo "$GHCR_TOKEN" | docker login ghcr.io -u github-actions --password-stdin >/dev/null
  echo "[i6] GHCR login OK"
fi
echo "[i6] pulling image: $WEB_IMAGE"
if ! docker pull "$WEB_IMAGE"; then
  echo "[i6] docker pull failed: $WEB_IMAGE"
  exit 35
fi
# Write WEB_IMAGE to env file so compose picks up the exact image tag.
if grep -q "^WEB_IMAGE=" "$ENV_FILE"; then
  sed -i "s|^WEB_IMAGE=.*|WEB_IMAGE=$WEB_IMAGE|" "$ENV_FILE"
else
  echo "WEB_IMAGE=$WEB_IMAGE" >> "$ENV_FILE"
fi
echo "[i6] WEB_IMAGE=$WEB_IMAGE written to $ENV_FILE"

# Phase 4: Swap web container only.
# --no-deps: do not touch db or redis.
# --force-recreate: ensure the new image is used even if compose thinks nothing changed.
# Downtime window = gunicorn startup time (~2-3s). For true zero-downtime a load
# balancer with multiple web replicas is needed (post-MVP scope).
echo "[i6] swapping web container (rolling restart)..."
if ! docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
  up -d --no-deps --force-recreate web; then
  echo "[i6] compose up failed for web"
  dump_compose_diagnostics
  exit 31
fi

# head -n1: defensive against a transient multi-id (old + new during recreate,
# or a leftover auraxis-web-run-* zombie). A multi-line $WEB_CID makes the later
# `docker exec "$WEB_CID" ...` target an invalid id and fail opaquely (exit 36).
WEB_CID="$(
  docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml \\
    ps -q web | head -n1 || true
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

# Apply pending Alembic migrations against the canonical DB.
# This runs inside the freshly-started web container, after the container is
# healthy (gunicorn up, DATABASE_URL connectable) but BEFORE the /healthz
# smoke check validates the deploy. Rationale: /healthz does not exercise
# schema-bound endpoints, so it passes even when the DB is N revisions behind
# the deployed code — meaning a broken schema would ship and only break on
# the first real request. Failing here aborts the deploy and blocks traffic.
# See issue #1252.
#
# IMPORTANT (#1405): we target the pinned container id "$WEB_CID" captured and
# health-validated right after --force-recreate, NOT "docker compose exec web".
# Re-resolving the "web" service by name can select a STALE one-off container
# (e.g. leftover auraxis-web-run-* from a prior `docker compose run`), whose
# image carries an OLDER migration set. Running upgrade there is a no-op and
# the drift gate then sees current==heads for the *old* head — so the deploy
# reports success while the live container serves new code against an
# un-migrated DB (the 2026-05-31 transactions outage: recurrence_* columns
# missing at alembic head ai6). Pinning to $WEB_CID makes this deterministic.
#
# We intentionally do NOT run this in rollback mode: rolling back schema is
# risky with multi-head merges and out-of-scope for the rollback path
# (forward-only migrations is the policy).
if [ "$MODE" = "deploy" ]; then
  echo "[i6] applying pending alembic migrations (flask db upgrade) in $WEB_CID..."
  echo "[i6] migrate target image=$(docker inspect --format '{{{{.Config.Image}}}}' "$WEB_CID" 2>&1)"
  ALEMBIC_STDERR="$(mktemp)"
  # Pin FLASK_APP=run.py: the running container leaves FLASK_APP empty, so a bare
  # `flask` relies on app auto-discovery, which can resolve to a context whose
  # migrations script_location is wrong → "Can't locate revision ..." (exit 36)
  # even when image + DB are correct. Setting it explicitly makes app→migrations
  # resolution deterministic (matches run.py:create_app).
  if ! docker exec -e FLASK_APP=run.py "$WEB_CID" \\
    flask db upgrade 2>"$ALEMBIC_STDERR"; then
    echo "[i6] alembic upgrade failed (web_cid=$WEB_CID)"
    # Dump compose diagnostics FIRST, then the alembic stderr LAST: the SSM
    # output is capped (~24KB, keeps the tail), so whatever prints last is what
    # survives. Printing the real error last makes exit-36 deploys diagnosable
    # from the CI log (2026-06-03 incident: the error was being truncated away).
    dump_compose_diagnostics
    echo "[i6] ===== alembic upgrade stderr (real failure cause) ====="
    cat "$ALEMBIC_STDERR" || true
    echo "[i6] ===== end alembic upgrade stderr ====="
    rm -f "$ALEMBIC_STDERR" || true
    exit 36
  fi
  rm -f "$ALEMBIC_STDERR" || true
  echo "[i6] alembic upgrade OK"

  # Drift gate: assert flask db current == flask db heads. Mirrors the
  # alembic_single_head CI gate but at deploy-time against the live DB. If
  # this fails the deploy has applied migrations but the resulting tip
  # diverges from the code's expected head — indicates alembic config drift
  # or a manual edit to the live DB. Abort before flipping traffic.
  CUR_REV="$(docker exec -e FLASK_APP=run.py "$WEB_CID" flask db current 2>/dev/null \\
    | awk '{{print $1}}' | tail -1)"
  HEAD_REV="$(docker exec -e FLASK_APP=run.py "$WEB_CID" flask db heads 2>/dev/null \\
    | awk '{{print $1}}' | tail -1)"
  echo "[i6] alembic current=$CUR_REV heads=$HEAD_REV"
  if [ -z "$CUR_REV" ] || [ -z "$HEAD_REV" ] || [ "$CUR_REV" != "$HEAD_REV" ]; then
    dump_compose_diagnostics
    # Print the drift verdict LAST so it survives the SSM output tail cap.
    echo "[i6] ===== alembic drift detected after upgrade ====="
    echo "[i6] current='$CUR_REV' heads='$HEAD_REV' — aborting before traffic flips."
    echo "[i6] ===== end alembic drift ====="
    exit 37
  fi
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
    python3 - <<'PY' "$STATE_PATH" "$STATE_CURRENT" "$WEB_IMAGE" "{schema_version}"
import json,sys
path=sys.argv[1]
prev=sys.argv[2] or ""
cur=sys.argv[3] or ""
schema_version=int(sys.argv[4])
data={{
  "schema_version": schema_version,
  "previous": prev,
  "current": cur,
}}
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
    p.add_argument(
        "--diagnostics-json-path",
        default="",
        help="Optional path to persist SSM invocation diagnostics as JSON.",
    )

    sub = p.add_subparsers(dest="cmd", required=True)
    p_deploy = sub.add_parser("deploy", help="Deploy a git ref to DEV/PROD.")
    p_deploy.add_argument("--env", choices=["dev", "prod"], required=True)
    p_deploy.add_argument("--git-ref", default="origin/master")
    p_deploy.add_argument(
        "--image",
        default="",
        help="Pre-built Docker image URI (GHCR) to deploy instead of building on EC2.",
    )
    p_deploy.add_argument(
        "--ghcr-token",
        default="",
        help="GitHub token for 'docker login ghcr.io' on the target EC2 instance.",
    )
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
        diagnostics_json_path = str(args.diagnostics_json_path or "") or None
        if mode == "deploy":
            git_ref = str(args.git_ref)
            comment_ref = f" ref={git_ref}"

        script = _build_script(
            env_name=env_name,
            aws_region=ctx.region,
            git_ref=git_ref,
            mode=mode,
            web_image=str(getattr(args, "image", "") or ""),
            ghcr_token=str(getattr(args, "ghcr_token", "") or ""),
        )
        cmd_id = ""
        try:
            cmd_id = _ssm_send_shell(
                ctx,
                instance_id,
                script,
                f"auraxis: i6 {mode} ({env_name}){comment_ref}",
            )
            print(f"{env_name.upper()} command_id={cmd_id}")
            invocation = _wait(ctx, command_id=cmd_id, instance_id=instance_id)
            report = _extract_invocation_report(
                invocation, instance_id=instance_id, command_id=cmd_id
            )
            report.update(
                {
                    "environment": env_name,
                    "mode": mode,
                    "git_ref": git_ref or "",
                }
            )
            _record_diagnostics(
                diagnostics_json_path=diagnostics_json_path,
                report=report,
            )
            return 0
        except SsmCommandFailed as exc:
            report = dict(exc.report)
            report.update(
                {
                    "environment": env_name,
                    "mode": mode,
                    "git_ref": git_ref or "",
                }
            )
            _record_diagnostics(
                diagnostics_json_path=diagnostics_json_path,
                report=report,
            )
            print(str(exc), file=sys.stderr)
            return 1
        except AwsCliError as exc:
            report = _build_generic_report(
                env_name=env_name,
                mode=mode,
                git_ref=git_ref,
                instance_id=instance_id,
                command_id=cmd_id or None,
                error=str(exc),
            )
            _record_diagnostics(
                diagnostics_json_path=diagnostics_json_path,
                report=report,
            )
            print(str(exc), file=sys.stderr)
            return 1

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
