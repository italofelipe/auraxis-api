#!/usr/bin/env python3
"""
Auraxis - Host firewall baseline (I8) via SSM.

Goal
- Apply a minimal, safe host firewall policy using UFW on EC2 instances:
  - default deny incoming
  - default allow outgoing
  - allow 80/tcp and 443/tcp
  - allow loopback

Why this exists
- Security Groups are the primary control in AWS, but a host firewall adds a
  second layer and reduces blast radius in case of SG mistakes.

Safety notes
- This script is designed to keep SSM working (outgoing allowed).
- It intentionally does NOT open SSH (22/tcp). Use SSM instead of SSH for ops.
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
        "TMP=/tmp/auraxis_ssm_ufw_i8_$$.sh; "
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
            stdout = str(out.get("StandardOutputContent") or "").strip()
            stderr = str(out.get("StandardErrorContent") or "").strip()
            raise AwsCliError(
                "SSM command failed. "
                f"instance_id={instance_id} command_id={command_id} status={status}\n"
                f"STDOUT:\n{stdout[-2000:]}\nSTDERR:\n{stderr[-2000:]}"
            )
        return out
    raise AwsCliError(
        "Timeout waiting SSM command. "
        f"instance_id={instance_id} command_id={command_id}"
    )


def _build_repo_detect() -> str:
    return """\
REPO=""
if [ -d /opt/auraxis ]; then
  REPO=/opt/auraxis
elif [ -d /opt/flask_expenses ]; then
  REPO=/opt/flask_expenses
else
  echo "Repo not found in /opt."
  exit 2
fi
cd "$REPO"
echo "[i8] repo=$REPO"
"""


def _build_apply_script(*, execute: bool) -> str:
    if not execute:
        return (
            "set -euo pipefail\n"
            + _build_repo_detect()
            + "echo '[i8] dry-run: would run scripts/ufw_hardening.sh'\n"
        )
    return (
        "set -euo pipefail\n" + _build_repo_detect() + "bash scripts/ufw_hardening.sh\n"
    )


def _build_status_script() -> str:
    return (
        "set -euo pipefail\n"
        + "if ! command -v ufw >/dev/null 2>&1; then "
        + "echo 'ufw not installed'; exit 3; fi\n"
        + "sudo ufw status verbose || true\n"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis UFW hardening (I8) via SSM")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)

    sub = p.add_subparsers(dest="cmd", required=True)
    p_apply = sub.add_parser("apply", help="Apply UFW baseline.")
    p_apply.add_argument("--env", choices=["prod", "dev"], required=True)
    p_apply.add_argument(
        "--execute",
        action="store_true",
        help="Apply for real. Without this flag, runs dry-run mode.",
    )
    p_apply.add_argument(
        "--print-output",
        action="store_true",
        help="Print SSM stdout/stderr on success (useful for auditing).",
    )

    p_status = sub.add_parser("status", help="Show UFW status on instance.")
    p_status.add_argument("--env", choices=["prod", "dev"], required=True)
    p_status.add_argument(
        "--print-output",
        action="store_true",
        help="Print SSM stdout/stderr on success.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)
    env_name = str(args.env)
    instance_id = args.prod_instance_id if env_name == "prod" else args.dev_instance_id

    if args.cmd == "apply":
        script = _build_apply_script(execute=bool(args.execute))
        cmd_id = _ssm_send_shell(
            ctx,
            instance_id,
            script,
            f"auraxis: i8 ufw apply ({env_name}) execute={bool(args.execute)}",
        )
        print(f"{env_name.upper()} command_id={cmd_id}")
        invocation = _wait(ctx, command_id=cmd_id, instance_id=instance_id)
        if bool(args.print_output):
            stdout = str(invocation.get("StandardOutputContent") or "").strip()
            stderr = str(invocation.get("StandardErrorContent") or "").strip()
            if stdout:
                print(stdout)
            if stderr:
                print(stderr)
        return 0

    if args.cmd == "status":
        script = _build_status_script()
        cmd_id = _ssm_send_shell(
            ctx, instance_id, script, f"auraxis: i8 ufw status ({env_name})"
        )
        print(f"{env_name.upper()} command_id={cmd_id}")
        invocation = _wait(ctx, command_id=cmd_id, instance_id=instance_id)
        if bool(args.print_output):
            stdout = str(invocation.get("StandardOutputContent") or "").strip()
            stderr = str(invocation.get("StandardErrorContent") or "").strip()
            if stdout:
                print(stdout)
            if stderr:
                print(stderr)
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
