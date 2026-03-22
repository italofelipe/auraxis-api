#!/usr/bin/env python3
"""
Auraxis - TLS renewal automation (I15).

What this does
- Installs a systemd timer + oneshot service on the EC2 instance to:
  - run certbot renew (docker compose) and reload nginx container

Why systemd (vs running certbot in a long-lived container)
- Host-level scheduling is more predictable and observable for a single-VM setup.
- We can keep the certbot image minimal and only run it when needed.

Notes
- DEV currently runs HTTP-only (until a dev certificate is provisioned). This installer
  should be used for PROD by default.
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


@dataclass(frozen=True)
class AwsCtx:
    profile: str
    region: str


class AwsCliError(RuntimeError):
    pass


def _run_aws(ctx: AwsCtx, args: list[str], *, expect_json: bool = True) -> Any:
    cmd = ["aws", "--profile", ctx.profile, "--region", ctx.region, *args]
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
        "TMP=/tmp/auraxis_ssm_tls_renew_i15_$$.sh; "
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
            raise AwsCliError(
                "SSM command failed. "
                f"instance_id={instance_id} command_id={command_id} status={status}\n"
                f"STDOUT:\n{stdout[-2000:]}\nSTDERR:\n{stderr[-2000:]}"
            )
        return
    raise AwsCliError(
        "Timeout waiting SSM command. "
        f"instance_id={instance_id} command_id={command_id}"
    )


def _build_install_script(*, repo_path: str | None) -> str:
    # systemd unit files live in the repo; we install them to /etc/systemd/system.
    preferred = repo_path or ""
    return f"""\
set -euo pipefail

REPO="{preferred}"
if [ -n "$REPO" ] && [ -d "$REPO" ]; then
  echo "[i15] repo=$REPO (explicit)"
elif [ -d /opt/auraxis ]; then
  REPO=/opt/auraxis
  echo "[i15] repo=$REPO"
elif [ -d /opt/flask_expenses ]; then
  REPO=/opt/flask_expenses
  echo "[i15] repo=$REPO (legacy)"
else
  echo "Repo not found in /opt."
  exit 2
fi
cd "$REPO"

sudo install -m 0644 deploy/systemd/auraxis-certbot-renew.service \
  /etc/systemd/system/auraxis-certbot-renew.service
sudo install -m 0644 deploy/systemd/auraxis-certbot-renew.timer \
  /etc/systemd/system/auraxis-certbot-renew.timer

sudo systemctl daemon-reload
sudo systemctl enable --now auraxis-certbot-renew.timer

echo "[i15] timer status:"
sudo systemctl status --no-pager auraxis-certbot-renew.timer || true
"""


def _build_run_once_script(*, repo_path: str | None, dry_run: bool) -> str:
    flag = "--dry-run" if dry_run else ""
    preferred = repo_path or ""
    return f"""\
set -euo pipefail

REPO="{preferred}"
if [ -n "$REPO" ] && [ -d "$REPO" ]; then
  echo "[i15] repo=$REPO (explicit)"
elif [ -d /opt/auraxis ]; then
  REPO=/opt/auraxis
  echo "[i15] repo=$REPO"
elif [ -d /opt/flask_expenses ]; then
  REPO=/opt/flask_expenses
  echo "[i15] repo=$REPO (legacy)"
else
  echo "Repo not found in /opt."
  exit 2
fi

cd "$REPO"
./scripts/renew_tls_cert.sh {flag}
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Auraxis TLS renewal automation (I15) via SSM"
    )
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)

    sub = p.add_subparsers(dest="cmd", required=True)
    p_install = sub.add_parser(
        "install", help="Install systemd timer+service for renewal."
    )
    p_install.add_argument("--env", choices=["prod", "dev"], default="prod")
    p_install.add_argument(
        "--repo-path",
        default=None,
        help=(
            "Optional override if repo is not under /opt/auraxis "
            "or /opt/flask_expenses."
        ),
    )

    p_run = sub.add_parser("run-once", help="Run renewal once via SSM.")
    p_run.add_argument("--env", choices=["prod", "dev"], default="prod")
    p_run.add_argument(
        "--repo-path",
        default=None,
        help=(
            "Optional override if repo is not under /opt/auraxis "
            "or /opt/flask_expenses."
        ),
    )
    p_run.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)
    env_name = str(getattr(args, "env", "prod"))
    instance_id = args.prod_instance_id if env_name == "prod" else args.dev_instance_id

    if args.cmd == "install":
        script = _build_install_script(repo_path=args.repo_path)
        cmd_id = _ssm_send_shell(
            ctx, instance_id, script, f"auraxis: i15 install ({env_name})"
        )
        print(f"{env_name.upper()} command_id={cmd_id}")
        _wait(ctx, command_id=cmd_id, instance_id=instance_id)
        return 0

    if args.cmd == "run-once":
        script = _build_run_once_script(
            repo_path=args.repo_path, dry_run=bool(args.dry_run)
        )
        cmd_id = _ssm_send_shell(
            ctx,
            instance_id,
            script,
            f"auraxis: i15 run-once ({env_name}) dry_run={bool(args.dry_run)}",
        )
        print(f"{env_name.upper()} command_id={cmd_id}")
        _wait(ctx, command_id=cmd_id, instance_id=instance_id)
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
