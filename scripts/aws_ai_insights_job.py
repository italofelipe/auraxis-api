#!/usr/bin/env python3
"""
Auraxis — AI Insights batch job runner via SSM (#1215, #1216).

Runs ``flask ai weekly-insights``, ``flask ai monthly-insights`` or
``flask ai spending-patterns`` inside the production Docker Compose network via
AWS SSM Send-Command.

Usage:
    python scripts/aws_ai_insights_job.py \\
        --mode weekly \\
        --region us-east-1 \\
        --env prod \\
        --instance-id i-0057e3b52162f78f8

    python scripts/aws_ai_insights_job.py \\
        --mode monthly \\
        --month 2026-04 \\          # optional, defaults to previous month
        --env prod
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
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


class SsmCommandFailed(AwsCliError):
    def __init__(self, report: dict[str, Any]):
        self.report = report
        super().__init__(_format_failure_message(report))


def _run_aws(ctx: AwsCtx, args: list[str], *, expect_json: bool = True) -> Any:
    cmd: list[str] = ["aws"]
    if ctx.profile:
        cmd.extend(["--profile", ctx.profile])
    if ctx.region:
        cmd.extend(["--region", ctx.region])
    cmd.extend(args)
    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise AwsCliError(
            (process.stderr or "").strip() or f"AWS CLI failed: {' '.join(cmd)}"
        )
    if not expect_json:
        return process.stdout
    stdout = (process.stdout or "").strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _ssm_send_shell(ctx: AwsCtx, instance_id: str, script: str, comment: str) -> str:
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    cmd = (
        "TMP=/tmp/auraxis_ssm_ai_insights_$$.sh; "
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
        f"AI insights job ({report.get('mode', '?')}) failed. "
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
    mode = str(report.get("mode") or "?")
    icon = "✅" if status == "Success" else "❌"
    lines = [
        f"### {icon} AI Insights Job ({mode}) via SSM",
        "",
        f"- Environment: `{report.get('environment', '')}`",
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


def _record_diagnostics(
    *, diagnostics_json_path: str | None, report: dict[str, Any]
) -> None:
    if diagnostics_json_path:
        _write_diagnostics_json(diagnostics_json_path, report)
    _append_github_summary(report)


def _wait(ctx: AwsCtx, *, command_id: str, instance_id: str) -> dict[str, Any]:
    deadline = time.time() + 1800  # 30-minute timeout (batch may run longer)
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
            time.sleep(10)
            continue
        if status != "Success":
            raise SsmCommandFailed(
                _extract_invocation_report(
                    out, instance_id=instance_id, command_id=command_id
                )
            )
        return dict(out)
    raise AwsCliError(
        "Timeout waiting for AI insights SSM command. "
        f"instance_id={instance_id} command_id={command_id}"
    )


def _build_script(*, env_name: str, mode: str, month: str | None = None) -> str:
    env_file = ".env.prod" if env_name == "prod" else ".env.dev"
    compose_file = (
        "docker-compose.prod.yml" if env_name == "prod" else "docker-compose.dev.yml"
    )

    if mode == "spending-patterns":
        flask_cmd = "flask ai spending-patterns"
    else:
        flask_cmd = f"flask ai {mode}-insights"
    if mode == "monthly" and month:
        flask_cmd += f" --month {month}"

    return f"""\
set -euo pipefail

REPO=""
CANONICAL_REPO=/opt/auraxis
LEGACY_REPO=/opt/flask_expenses

if [ -d "$CANONICAL_REPO/.git" ] || [ -f "$CANONICAL_REPO/.git" ]; then
  REPO="$CANONICAL_REPO"
elif [ -d "$LEGACY_REPO/.git" ] || [ -f "$LEGACY_REPO/.git" ]; then
  REPO="$LEGACY_REPO"
fi

if [ -z "$REPO" ]; then
  echo "[ai-insights] repo not found in /opt"
  exit 2
fi

cd "$REPO"
echo "[ai-insights] repo=$REPO env={env_name} mode={mode}"

ENV_FILE="{env_file}"
COMPOSE_FILE="{compose_file}"

require_file() {{
  path="$1"
  if [ ! -f "$path" ]; then
    echo "[ai-insights] missing required file: $path"
    exit 3
  fi
}}

require_cmd() {{
  cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[ai-insights] missing command: $cmd"
    exit 4
  fi
}}

require_file "$ENV_FILE"
require_file "$COMPOSE_FILE"
require_cmd docker

if ! docker info >/dev/null 2>&1; then
  echo "[ai-insights] docker daemon unavailable"
  exit 5
fi

COMPOSE_SERVICES="$(
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --services
)"

service_is_defined() {{
  service="$1"
  printf '%s\n' "$COMPOSE_SERVICES" | grep -Fxq "$service"
}}

SERVICE_START_ARGS=()
for SERVICE in db redis; do
  if service_is_defined "$SERVICE"; then
    SERVICE_START_ARGS+=("$SERVICE")
  else
    echo "[ai-insights] skipping $SERVICE; not defined in compose"
  fi
done

if [ "${{#SERVICE_START_ARGS[@]}}" -gt 0 ]; then
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" \\
    up -d "${{SERVICE_START_ARGS[@]}}"
else
  echo "[ai-insights] no optional infrastructure services to start"
fi

INSPECT_HEALTH='{{{{if .State.Health}}}}{{{{.State.Health.Status}}}}\
{{{{else}}}}{{{{.State.Status}}}}{{{{end}}}}'

for SERVICE in "${{SERVICE_START_ARGS[@]}}"; do
  CID=""
  for _ in $(seq 1 30); do
    CID="$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -q "$SERVICE")"
    HEALTH="$(
      docker inspect -f "$INSPECT_HEALTH" "$CID" 2>/dev/null || true
    )"
    if [ -n "$CID" ] && [ "$HEALTH" = "healthy" -o "$HEALTH" = "running" ]; then
      break
    fi
    sleep 2
  done
  if [ -z "$CID" ]; then
    echo "[ai-insights] $SERVICE container was not created or is not running"
    exit 6
  fi
done

# Issue #1249: exec the CLI inside the *running* web container instead of
# `docker compose run`. The prod ENTRYPOINT (scripts/entrypoint_prod.sh) always
# `exec gunicorn ...` and ignores any passed command, so `run web <cmd>` booted
# a web server that never exited and the SSM wait timed out (~30 min) on every
# scheduled run. `exec` runs the command in the live container — which also
# carries the correct DATABASE_URL / LLM_PROVIDER the API actually serves with
# (the `run` path used .env.prod, still pointing at the decommissioned RDS) —
# and exits cleanly when the batch finishes.
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T \\
  -e FLASK_APP=run.py \\
  web {flask_cmd}
"""


def run_once(
    *,
    ctx: AwsCtx,
    mode: str,
    env_name: str,
    instance_id: str,
    month: str | None = None,
    diagnostics_json_path: str | None = None,
) -> dict[str, Any]:
    command_id = _ssm_send_shell(
        ctx,
        instance_id,
        _build_script(env_name=env_name, mode=mode, month=month),
        f"auraxis: ai-insights {mode} ({env_name})",
    )
    try:
        invocation = _wait(ctx, command_id=command_id, instance_id=instance_id)
        report = {
            "mode": mode,
            "environment": env_name,
            **_extract_invocation_report(
                invocation, instance_id=instance_id, command_id=command_id
            ),
        }
    except SsmCommandFailed as exc:
        report = {"mode": mode, "environment": env_name, **exc.report}
        _record_diagnostics(
            diagnostics_json_path=diagnostics_json_path,
            report=report,
        )
        raise

    _record_diagnostics(
        diagnostics_json_path=diagnostics_json_path,
        report=report,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Auraxis AI Insights batch job via SSM."
    )
    parser.add_argument(
        "--mode",
        choices=["weekly", "monthly", "spending-patterns"],
        required=True,
        help="Which batch job to run: 'weekly', 'monthly' or 'spending-patterns'.",
    )
    parser.add_argument(
        "--month",
        default="",
        metavar="YYYY-MM",
        help="Month for monthly mode. Defaults to previous calendar month.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AWS_PROFILE", DEFAULT_PROFILE),
        help="AWS profile. Empty string uses env/OIDC credentials.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", DEFAULT_REGION),
        help="AWS region.",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="prod",
        help="Target environment.",
    )
    parser.add_argument(
        "--instance-id",
        default="",
        help="Target EC2 instance id. Defaults to env-specific built-in.",
    )
    parser.add_argument(
        "--diagnostics-json-path",
        default="",
        help="Optional path for diagnostics JSON artifact.",
    )
    args = parser.parse_args()

    instance_id = args.instance_id or (
        DEFAULT_PROD_INSTANCE_ID if args.env == "prod" else DEFAULT_DEV_INSTANCE_ID
    )
    ctx = AwsCtx(profile=args.profile, region=args.region)
    run_once(
        ctx=ctx,
        mode=args.mode,
        env_name=args.env,
        instance_id=instance_id,
        month=args.month or None,
        diagnostics_json_path=args.diagnostics_json_path or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
