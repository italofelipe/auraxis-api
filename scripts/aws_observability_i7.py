#!/usr/bin/env python3
"""
Auraxis - Observability Baseline (I7) via AWS CLI.

This script is intentionally small and idempotent. It focuses on:
1) CloudWatch alarms for memory and disk usage (from CloudWatch Agent metrics)
2) Updating the existing `Auraxis-EC2` dashboard to include mem/disk widgets

Why it exists
- We want infra observability "as code" so CI + review can catch regressions.
- We want repeatable setup for DEV/PROD without manual click-ops.

Prerequisites
- AWS CLI authenticated locally (AWS SSO profile recommended).
- CloudWatch Agent already installed+configured on instances and publishing to
  the `Auraxis/EC2` namespace (see `scripts/aws_cloudwatch_agent.py`).
- SNS topic `auraxis-alerts` exists (created in S1 earlier) for notifications.

Notes
- We keep thresholds conservative for tiny instances (t2.micro):
  - mem_used_percent >= 90
  - disk_used_percent >= 85
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:765480282720:auraxis-alerts"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"

NAMESPACE = "Auraxis/EC2"


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


def _dimensions_to_cli(dimensions: Iterable[dict[str, str]]) -> list[str]:
    out: list[str] = []
    for d in dimensions:
        out.append(f"Name={d['Name']},Value={d['Value']}")
    return out


def _alarm_name(instance_id: str, metric: str) -> str:
    return f"auraxis-{instance_id}-{metric}"


def _put_alarm(
    ctx: AwsCtx,
    *,
    alarm_name: str,
    metric_name: str,
    dimensions: list[dict[str, str]],
    threshold: float,
    sns_topic_arn: str,
    description: str,
) -> None:
    _run_aws(
        ctx,
        [
            "cloudwatch",
            "put-metric-alarm",
            "--alarm-name",
            alarm_name,
            "--alarm-description",
            description,
            "--namespace",
            NAMESPACE,
            "--metric-name",
            metric_name,
            "--dimensions",
            *_dimensions_to_cli(dimensions),
            "--statistic",
            "Average",
            "--period",
            "60",
            "--evaluation-periods",
            "5",
            "--datapoints-to-alarm",
            "3",
            "--threshold",
            str(threshold),
            "--comparison-operator",
            "GreaterThanOrEqualToThreshold",
            "--treat-missing-data",
            "missing",
            "--alarm-actions",
            sns_topic_arn,
            "--ok-actions",
            sns_topic_arn,
            "--insufficient-data-actions",
            sns_topic_arn,
        ],
        expect_json=False,
    )


def ensure_mem_disk_alarms(
    ctx: AwsCtx,
    *,
    instance_id: str,
    instance_type: str,
    sns_topic_arn: str,
    disk_device: str = "xvda1",
    disk_fstype: str = "ext4",
    disk_path: str = "/",
    mem_threshold: float = 90.0,
    disk_threshold: float = 85.0,
) -> None:
    """
    Create/overwrite alarms for mem/disk usage for a single instance.

    Metric dimensions must match the emitted metrics, otherwise the alarm never
    evaluates. For our current CW Agent config:
    - mem_used_percent dimensions: InstanceId, InstanceType
    - disk_used_percent dimensions: path, device, fstype, InstanceId, InstanceType
    """
    mem_dims = [
        {"Name": "InstanceId", "Value": instance_id},
        {"Name": "InstanceType", "Value": instance_type},
    ]
    disk_dims = [
        {"Name": "path", "Value": disk_path},
        {"Name": "InstanceId", "Value": instance_id},
        {"Name": "InstanceType", "Value": instance_type},
        {"Name": "device", "Value": disk_device},
        {"Name": "fstype", "Value": disk_fstype},
    ]

    _put_alarm(
        ctx,
        alarm_name=_alarm_name(instance_id, "MemUsedHigh"),
        metric_name="mem_used_percent",
        dimensions=mem_dims,
        threshold=mem_threshold,
        sns_topic_arn=sns_topic_arn,
        description=(
            f"Auraxis: High memory usage on {instance_id} (>= {mem_threshold}%)"
        ),
    )
    _put_alarm(
        ctx,
        alarm_name=_alarm_name(instance_id, "DiskUsedHigh"),
        metric_name="disk_used_percent",
        dimensions=disk_dims,
        threshold=disk_threshold,
        sns_topic_arn=sns_topic_arn,
        description=f"Auraxis: High disk usage on {instance_id} (>= {disk_threshold}%)",
    )


def _load_dashboard(ctx: AwsCtx, name: str) -> dict[str, Any]:
    out = _run_aws(ctx, ["cloudwatch", "get-dashboard", "--dashboard-name", name])
    body = out.get("DashboardBody") or "{}"
    return json.loads(body)


def _put_dashboard(ctx: AwsCtx, name: str, body: dict[str, Any]) -> None:
    _run_aws(
        ctx,
        [
            "cloudwatch",
            "put-dashboard",
            "--dashboard-name",
            name,
            "--dashboard-body",
            json.dumps(body),
        ],
        expect_json=False,
    )


def update_dashboard_with_mem_disk(
    ctx: AwsCtx,
    *,
    dashboard_name: str,
    dev_instance_id: str,
    prod_instance_id: str,
) -> None:
    """
    Update the existing dashboard to include mem/disk widgets.

    We append widgets; we do not try to "auto-layout" aggressively to avoid
    breaking an existing visual layout.
    """
    body = _load_dashboard(ctx, dashboard_name)
    widgets = body.setdefault("widgets", [])

    def widget(title: str, metric: list[Any], x: int, y: int) -> dict[str, Any]:
        return {
            "type": "metric",
            "x": x,
            "y": y,
            "width": 12,
            "height": 6,
            "properties": {
                "region": ctx.region,
                "title": title,
                "view": "timeSeries",
                "stat": "Average",
                "period": 60,
                "metrics": [metric],
                "yAxis": {"left": {"min": 0, "max": 100}},
            },
        }

    # Place new widgets below existing ones (best-effort). If there are no widgets,
    # start at (0,0).
    max_y = 0
    for w in widgets:
        try:
            max_y = max(max_y, int(w.get("y", 0)) + int(w.get("height", 0)))
        except Exception:
            pass

    y0 = max_y + 1
    widgets.append(
        widget(
            f"DEV mem_used_percent ({dev_instance_id})",
            [NAMESPACE, "mem_used_percent", "InstanceId", dev_instance_id],
            0,
            y0,
        )
    )
    widgets.append(
        widget(
            f"PROD mem_used_percent ({prod_instance_id})",
            [NAMESPACE, "mem_used_percent", "InstanceId", prod_instance_id],
            12,
            y0,
        )
    )
    widgets.append(
        widget(
            f"DEV disk_used_percent ({dev_instance_id})",
            [
                NAMESPACE,
                "disk_used_percent",
                "InstanceId",
                dev_instance_id,
                "path",
                "/",
            ],
            0,
            y0 + 6,
        )
    )
    widgets.append(
        widget(
            f"PROD disk_used_percent ({prod_instance_id})",
            [
                NAMESPACE,
                "disk_used_percent",
                "InstanceId",
                prod_instance_id,
                "path",
                "/",
            ],
            12,
            y0 + 6,
        )
    )

    _put_dashboard(ctx, dashboard_name, body)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis observability baseline (I7)")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--sns-topic-arn", default=DEFAULT_SNS_TOPIC_ARN)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dashboard-name", default="Auraxis-EC2")
    p.add_argument(
        "--instance-type",
        default="t2.micro",
        help="InstanceType dimension used by CW Agent metrics (default: t2.micro).",
    )
    p.add_argument("--mem-threshold", type=float, default=90.0)
    p.add_argument("--disk-threshold", type=float, default=85.0)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("alarms", help="Create/overwrite DEV+PROD mem/disk alarms.")

    sub.add_parser(
        "dashboard", help="Append mem/disk widgets to Auraxis-EC2 dashboard."
    )
    sub.add_parser("apply", help="Run alarms + dashboard.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)

    if args.cmd in {"alarms", "apply"}:
        ensure_mem_disk_alarms(
            ctx,
            instance_id=args.dev_instance_id,
            instance_type=args.instance_type,
            sns_topic_arn=args.sns_topic_arn,
            mem_threshold=args.mem_threshold,
            disk_threshold=args.disk_threshold,
        )
        ensure_mem_disk_alarms(
            ctx,
            instance_id=args.prod_instance_id,
            instance_type=args.instance_type,
            sns_topic_arn=args.sns_topic_arn,
            mem_threshold=args.mem_threshold,
            disk_threshold=args.disk_threshold,
        )

    if args.cmd in {"dashboard", "apply"}:
        update_dashboard_with_mem_disk(
            ctx,
            dashboard_name=args.dashboard_name,
            dev_instance_id=args.dev_instance_id,
            prod_instance_id=args.prod_instance_id,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
