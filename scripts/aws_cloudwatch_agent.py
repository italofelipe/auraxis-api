#!/usr/bin/env python3
"""
Auraxis - CloudWatch Agent bootstrap (EC2) via SSM.

Why this exists
- Default EC2 metrics do not include memory/disk usage.
- For a small project, CloudWatch Agent provides a pragmatic baseline:
  - memory_used_percent
  - disk_used_percent (root filesystem)
  - optional log shipping (syslog/auth) later

How it works
- No SSH is used. All instance-side operations are executed via AWS SSM.
- We install the agent using the SSM document `AWS-ConfigureAWSPackage`
  (`AmazonCloudWatchAgent` package).
- We push a minimal config file and start the agent.

Operator prerequisites
- AWS CLI auth working locally (AWS SSO recommended).
- Instances must be SSM-managed and have permissions to publish CW metrics:
  the instance role should include `CloudWatchAgentServerPolicy`.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
from dataclasses import dataclass
from typing import Any

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"


@dataclass(frozen=True)
class AwsCtx:
    """Immutable context for AWS CLI operations."""

    profile: str
    region: str


class AwsCliError(RuntimeError):
    """Raised when an `aws ...` CLI invocation fails."""


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


def _ssm_send_shell(
    ctx: AwsCtx, instance_ids: list[str], script: str, comment: str
) -> str:
    """
    Send a single shell script to instances via AWS-RunShellScript.

    We ship the script as base64 and execute with `bash` for deterministic behavior.
    """
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    cmd = (
        "TMP=/tmp/auraxis_ssm_cwagent_$$.sh; "
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
            *instance_ids,
            "--document-name",
            "AWS-RunShellScript",
            "--comment",
            comment,
            "--parameters",
            payload,
        ],
        expect_json=True,
    )
    return str(out["Command"]["CommandId"])


def install_agent(ctx: AwsCtx, instance_ids: list[str]) -> str:
    """
    Install `AmazonCloudWatchAgent` using AWS-ConfigureAWSPackage.

    This is the most reliable install method across Ubuntu AMIs.
    """
    out = _run_aws(
        ctx,
        [
            "ssm",
            "send-command",
            "--instance-ids",
            *instance_ids,
            "--document-name",
            "AWS-ConfigureAWSPackage",
            "--comment",
            "auraxis: install cloudwatch agent package",
            "--parameters",
            json.dumps(
                {
                    "action": ["Install"],
                    "name": ["AmazonCloudWatchAgent"],
                    "version": ["latest"],
                }
            ),
        ],
        expect_json=True,
    )
    return str(out["Command"]["CommandId"])


def configure_and_start(
    ctx: AwsCtx,
    *,
    instance_ids: list[str],
    namespace: str = "Auraxis/EC2",
    env: str = "unknown",
) -> str:
    """
    Push a minimal config and start the agent.

    The config is intentionally small and predictable to reduce operational risk.
    """
    # Root FS metrics only. Add more disks/logs later if needed.
    config = {
        "agent": {"metrics_collection_interval": 60, "run_as_user": "root"},
        "metrics": {
            "namespace": namespace,
            "append_dimensions": {
                "InstanceId": "${aws:InstanceId}",
                "InstanceType": "${aws:InstanceType}",
                "AutoScalingGroupName": "${aws:AutoScalingGroupName}",
                "Environment": env,
                "App": "auraxis",
            },
            "metrics_collected": {
                "mem": {"measurement": ["mem_used_percent"]},
                "disk": {
                    "measurement": ["used_percent"],
                    "resources": ["/"],
                    "ignore_file_system_types": ["sysfs", "devtmpfs", "tmpfs"],
                },
            },
        },
    }

    script = f"""\
set -euo pipefail

CONFIG=/tmp/auraxis-cwagent.json
cat > "$CONFIG" <<'JSON'
{json.dumps(config, indent=2, sort_keys=True)}
JSON

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \\
  -a fetch-config -m ec2 -c file:"$CONFIG" -s

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status || true
"""
    return _ssm_send_shell(
        ctx, instance_ids, script, "auraxis: configure+start cloudwatch agent"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis CloudWatch Agent via SSM")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("install", help="Install the agent package on DEV+PROD.")

    p_cfg = sub.add_parser("configure", help="Configure + start the agent on DEV+PROD.")
    p_cfg.add_argument("--namespace", default="Auraxis/EC2")

    sub.add_parser("status", help="Print agent status (DEV+PROD).")
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)
    iids = [args.dev_instance_id, args.prod_instance_id]

    if args.cmd == "install":
        print(install_agent(ctx, iids))
        return 0

    if args.cmd == "configure":
        # Configure DEV and PROD separately, so `Environment` dimension is correct.
        print(
            configure_and_start(
                ctx,
                instance_ids=[args.dev_instance_id],
                namespace=args.namespace,
                env="dev",
            )
        )
        print(
            configure_and_start(
                ctx,
                instance_ids=[args.prod_instance_id],
                namespace=args.namespace,
                env="prod",
            )
        )
        return 0

    if args.cmd == "status":
        script = """\
set -euo pipefail
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status || true
"""
        print(_ssm_send_shell(ctx, iids, script, "auraxis: cloudwatch agent status"))
        return 0

    raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
