#!/usr/bin/env python3
"""
Auraxis - EventBridge -> SNS alerts for SSM command failures.

Problem
- We run critical operational actions via SSM (patching, backups, hardening).
- If those commands fail silently, we lose "operational safety".

Solution
- Create an EventBridge rule that listens for SSM RunCommand status changes
  where status is a failure state.
- Filter to only our DEV/PROD instance ids.
- Send the full event payload to the existing SNS topic `auraxis-alerts`.

Why this is useful
- It covers patching (Maintenance Window tasks), ad-hoc operational commands,
  and any future SSM-based automations.
- It does not require an always-on agent, and costs are negligible.

Prerequisites
- SNS topic exists: `auraxis-alerts`
- AWS CLI authenticated locally (AWS SSO recommended).

References
- Event type: "EC2 Command Status-change Notification"
  source: "aws.ssm"
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from typing import Any

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:765480282720:auraxis-alerts"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"

RULE_NAME = "auraxis-ssm-command-failures"


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


def _ensure_sns_publish_policy(ctx: AwsCtx, topic_arn: str) -> None:
    """
    Ensure SNS topic policy allows EventBridge to publish.

    Without this, EventBridge targets can be created but deliveries fail.
    """
    attrs = _run_aws(
        ctx,
        ["sns", "get-topic-attributes", "--topic-arn", topic_arn],
        expect_json=True,
    )
    policy_raw = (attrs.get("Attributes") or {}).get("Policy") or ""
    if policy_raw.strip():
        policy = json.loads(policy_raw)
    else:
        policy = {"Version": "2012-10-17", "Statement": []}

    # SNS policies commonly use "Sid" for idempotency.
    sid = "AllowEventBridgePublish"
    for st in policy.get("Statement", []):
        if st.get("Sid") == sid:
            return

    statement = {
        "Sid": sid,
        "Effect": "Allow",
        "Principal": {"Service": "events.amazonaws.com"},
        "Action": "sns:Publish",
        "Resource": topic_arn,
    }
    policy.setdefault("Statement", []).append(statement)

    _run_aws(
        ctx,
        [
            "sns",
            "set-topic-attributes",
            "--topic-arn",
            topic_arn,
            "--attribute-name",
            "Policy",
            "--attribute-value",
            json.dumps(policy),
        ],
        expect_json=False,
    )


def ensure_rule(ctx: AwsCtx, *, instance_ids: list[str]) -> str:
    """
    Ensure the EventBridge rule exists and return its ARN.

    We match failing statuses only, and scope to our instances.
    """
    event_pattern = {
        "source": ["aws.ssm"],
        "detail-type": ["EC2 Command Status-change Notification"],
        "detail": {
            "instance-id": instance_ids,
            "status": ["Failed", "TimedOut", "Cancelled"],
        },
    }

    out = _run_aws(
        ctx,
        [
            "events",
            "put-rule",
            "--name",
            RULE_NAME,
            "--description",
            "Auraxis: alert on SSM RunCommand failures for DEV/PROD instances",
            "--event-pattern",
            json.dumps(event_pattern),
            "--state",
            "ENABLED",
        ],
        expect_json=True,
    )
    return str(out["RuleArn"])


def ensure_target(ctx: AwsCtx, *, rule_name: str, topic_arn: str) -> None:
    """
    Ensure the SNS target is configured on the rule.
    """
    target_id = "auraxis-alerts-sns"
    _run_aws(
        ctx,
        [
            "events",
            "put-targets",
            "--rule",
            rule_name,
            "--targets",
            json.dumps([{"Id": target_id, "Arn": topic_arn}]),
        ],
        expect_json=True,
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis EventBridge->SNS alerts")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--sns-topic-arn", default=DEFAULT_SNS_TOPIC_ARN)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)
    instance_ids = [args.dev_instance_id, args.prod_instance_id]

    _ensure_sns_publish_policy(ctx, args.sns_topic_arn)
    rule_arn = ensure_rule(ctx, instance_ids=instance_ids)
    ensure_target(ctx, rule_name=RULE_NAME, topic_arn=args.sns_topic_arn)

    print(rule_arn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
