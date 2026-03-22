#!/usr/bin/env python3
"""
Auraxis - Validation checklist (I16).

This script implements a repeatable, CI-like validation checklist for:
- DNS
- HTTPS/HTTP reachability for DEV/PROD
- SSM connectivity
- Instance-side health (/healthz) and docker compose status
- Route53 health check + CloudWatch alarm state
- CloudWatch Logs basic presence (log groups)
- Backups bucket existence

It is intentionally read-only.
"""

from __future__ import annotations

import argparse
import base64
import json
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"

DEFAULT_PROD_DOMAIN = "api.auraxis.com.br"
DEFAULT_DEV_DOMAIN = "dev.api.auraxis.com.br"

DEFAULT_BACKUP_BUCKET = "auraxis-backups-765480282720"

# Known health check IDs created earlier (I7). These may change if recreated.
DEFAULT_PROD_HEALTHCHECK_ID = "feaaae1d-df01-4854-bef2-951498c125ea"
DEFAULT_DEV_HEALTHCHECK_ID = "393706bf-ae1c-4109-9c9d-71f1b108b767"

# Known CloudWatch alarms created earlier (I7).
DEFAULT_PROD_ALARM_NAME = "auraxis-health-prod"
DEFAULT_DEV_ALARM_NAME = "auraxis-health-dev"


@dataclass(frozen=True)
class AwsCtx:
    profile: str
    region: str


class CheckFailed(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _run_aws(ctx: AwsCtx, args: list[str], *, expect_json: bool = True) -> Any:
    p = _run(["aws", "--profile", ctx.profile, "--region", ctx.region, *args])
    if p.returncode != 0:
        raise CheckFailed((p.stderr or "").strip() or "aws cli failed")
    if not expect_json:
        return p.stdout
    stdout = (p.stdout or "").strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _ssm_send_shell(ctx: AwsCtx, instance_id: str, script: str, comment: str) -> str:
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    cmd = (
        "TMP=/tmp/auraxis_ssm_validate_i16_$$.sh; "
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


def _ssm_wait(ctx: AwsCtx, *, command_id: str, instance_id: str) -> dict[str, Any]:
    deadline = time.time() + 900
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
            time.sleep(3)
            continue
        if status != "Success":
            stdout = str(out.get("StandardOutputContent") or "").strip()
            stderr = str(out.get("StandardErrorContent") or "").strip()
            raise CheckFailed(
                "ssm failed "
                f"status={status}\nSTDOUT:\n{stdout[-2000:]}\nSTDERR:\n{stderr[-2000:]}"
            )
        return out
    raise CheckFailed("timeout waiting ssm command")


def _print_ok(msg: str) -> None:
    print(f"[PASS] {msg}")


def _print_warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def _print_fail(msg: str) -> None:
    print(f"[FAIL] {msg}")


def _resolve_a(domain: str) -> list[str]:
    infos = socket.getaddrinfo(domain, 80, proto=socket.IPPROTO_TCP)
    ips = sorted({str(i[4][0]) for i in infos if i and i[4]})
    return ips


def _http_head(url: str, *, timeout: int = 8) -> int:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status)


def check_dns(*, domain: str) -> None:
    ips = _resolve_a(domain)
    if not ips:
        raise CheckFailed(f"dns: no A/AAAA records for {domain}")
    _print_ok(f"dns: {domain} resolves to {', '.join(ips)}")


def check_http(*, url: str) -> None:
    code = _http_head(url)
    if code < 200 or code >= 400:
        raise CheckFailed(f"http: {url} returned status {code}")
    _print_ok(f"http: {url} status={code}")


def check_bucket(ctx: AwsCtx, bucket: str) -> None:
    _run_aws(ctx, ["s3api", "head-bucket", "--bucket", bucket], expect_json=False)
    _print_ok(f"s3: bucket exists: {bucket}")


def check_route53_health(ctx: AwsCtx, *, healthcheck_id: str, label: str) -> None:
    out = _run_aws(
        ctx, ["route53", "get-health-check-status", "--health-check-id", healthcheck_id]
    )
    obs = out.get("HealthCheckObservations") or []
    if not obs:
        _print_warn(
            f"route53: no observations for {label} healthcheck={healthcheck_id}"
        )
        return
    # API returns StatusReport.Status as a string like:
    # "Success: HTTP Status Code 200, OK. Resolved IP: ..."
    # We'll consider it healthy if any observation string starts with "Success:".
    for o in obs:
        status = str((o.get("StatusReport") or {}).get("Status") or "")
        if status.startswith("Success:"):
            _print_ok(f"route53: {label} healthcheck healthy: {healthcheck_id}")
            return
    raise CheckFailed(f"route53: {label} healthcheck not healthy: {healthcheck_id}")


def check_alarm_ok(ctx: AwsCtx, *, alarm_name: str, label: str) -> None:
    out = _run_aws(ctx, ["cloudwatch", "describe-alarms", "--alarm-names", alarm_name])
    alarms = out.get("MetricAlarms") or []
    if not alarms:
        _print_warn(f"cloudwatch: alarm not found: {label} alarm={alarm_name}")
        return
    state = str(alarms[0].get("StateValue") or "UNKNOWN")
    if state != "OK":
        raise CheckFailed(
            f"cloudwatch: {label} alarm not OK: {alarm_name} state={state}"
        )
    _print_ok(f"cloudwatch: {label} alarm OK: {alarm_name}")


def check_log_group(ctx: AwsCtx, *, group: str) -> None:
    out = _run_aws(
        ctx, ["logs", "describe-log-groups", "--log-group-name-prefix", group]
    )
    groups = out.get("logGroups") or []
    if not any(str(g.get("logGroupName")) == group for g in groups):
        raise CheckFailed(f"logs: log group not found: {group}")
    _print_ok(f"logs: log group exists: {group}")


def check_instance_side(ctx: AwsCtx, *, instance_id: str, label: str) -> None:
    script = """\
set -euo pipefail
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
echo "[i16] repo=$REPO"
docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1/healthz >/dev/null
echo "[i16] healthz ok"
"""
    cmd_id = _ssm_send_shell(
        ctx, instance_id, script, f"auraxis: i16 validate ({label})"
    )
    inv = _ssm_wait(ctx, command_id=cmd_id, instance_id=instance_id)
    stdout = str(inv.get("StandardOutputContent") or "").strip()
    if "healthz ok" not in stdout:
        raise CheckFailed(f"ssm: {label} did not validate healthz")
    _print_ok(f"ssm: {label} compose+healthz ok (instance {instance_id})")


def _iter_targets(targets: Iterable[str]) -> list[str]:
    uniq: list[str] = []
    for t in targets:
        if t not in uniq:
            uniq.append(t)
    return uniq


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis validation checklist (I16)")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)
    p.add_argument("--prod-domain", default=DEFAULT_PROD_DOMAIN)
    p.add_argument("--dev-domain", default=DEFAULT_DEV_DOMAIN)
    p.add_argument("--backup-bucket", default=DEFAULT_BACKUP_BUCKET)
    p.add_argument("--prod-healthcheck-id", default=DEFAULT_PROD_HEALTHCHECK_ID)
    p.add_argument("--dev-healthcheck-id", default=DEFAULT_DEV_HEALTHCHECK_ID)
    p.add_argument("--prod-alarm-name", default=DEFAULT_PROD_ALARM_NAME)
    p.add_argument("--dev-alarm-name", default=DEFAULT_DEV_ALARM_NAME)
    p.add_argument(
        "--target",
        action="append",
        default=[],
        choices=["dns", "http", "ssm", "route53", "logs", "s3"],
        help="Optional: run only specific checks (repeatable). Default: all.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)
    targets = _iter_targets(args.target) or [
        "dns",
        "http",
        "ssm",
        "route53",
        "logs",
        "s3",
    ]

    try:
        if "dns" in targets:
            check_dns(domain=str(args.prod_domain))
            check_dns(domain=str(args.dev_domain))

        if "http" in targets:
            check_http(url=f"https://{args.prod_domain}/healthz")
            # DEV is HTTP-only for now.
            check_http(url=f"http://{args.dev_domain}/healthz")

        if "ssm" in targets:
            check_instance_side(
                ctx, instance_id=str(args.prod_instance_id), label="prod"
            )
            check_instance_side(ctx, instance_id=str(args.dev_instance_id), label="dev")

        if "route53" in targets:
            check_route53_health(
                ctx, healthcheck_id=str(args.prod_healthcheck_id), label="prod"
            )
            check_route53_health(
                ctx, healthcheck_id=str(args.dev_healthcheck_id), label="dev"
            )
            check_alarm_ok(ctx, alarm_name=str(args.prod_alarm_name), label="prod")
            check_alarm_ok(ctx, alarm_name=str(args.dev_alarm_name), label="dev")

        if "logs" in targets:
            check_log_group(ctx, group="/auraxis/prod/containers")
            check_log_group(ctx, group="/auraxis/dev/containers")

        if "s3" in targets:
            check_bucket(ctx, bucket=str(args.backup_bucket))

    except CheckFailed as exc:
        _print_fail(str(exc))
        return 2

    _print_ok("i16 validation complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
