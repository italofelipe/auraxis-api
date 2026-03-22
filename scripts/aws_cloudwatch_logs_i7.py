#!/usr/bin/env python3
"""
Auraxis - CloudWatch Logs baseline (I7) via AWS CLI.

Goal
- Provide centralized logs (without SSH) for DEV/PROD EC2 Docker workloads.

Approach
- We prefer Docker's `awslogs` logging driver (configured via an overlay compose):
  `docker-compose.aws.logging.yml`
- This script prepares the AWS side:
  1) Ensure the instances' IAM role has CloudWatch Logs permissions.
     We attach the AWS-managed policy `CloudWatchAgentServerPolicy`, which
     includes CloudWatch Logs permissions required by `awslogs`.
  2) Ensure log groups exist for DEV/PROD and apply a retention policy to keep
     costs predictable.

Why not "tail /var/lib/docker/containers/*/*.log" with the agent?
- It is noisier, harder to scope to only our services, and error-prone with
  container churn. The `awslogs` driver ships per-container stdout/stderr in a
  controlled way.

Operator prerequisites
- AWS CLI authenticated locally (AWS SSO profile recommended).
- Instances are running with an instance profile role (not bare instances).

Safe-by-default
- All operations are idempotent.
- We avoid editing instance OS state. This script only touches IAM + Logs.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from typing import Any

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"

DEFAULT_POLICY_ARN = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"

# Retention: keep costs low. Tune later.
DEV_RETENTION_DAYS = 7
PROD_RETENTION_DAYS = 30


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


def _try_run_aws(ctx: AwsCtx, args: list[str]) -> tuple[bool, str]:
    cmd = ["aws", "--profile", ctx.profile, "--region", ctx.region, *args]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        return False, (p.stderr or p.stdout or "").strip()
    return True, (p.stdout or "").strip()


def _get_instance_role_name(ctx: AwsCtx, instance_id: str) -> str:
    """
    Resolve the IAM role name from an EC2 instance ID.

    We follow:
      EC2 Instance -> IamInstanceProfile.Arn -> instance profile name ->
      iam get-instance-profile -> Roles[0].RoleName
    """
    desc = _run_aws(ctx, ["ec2", "describe-instances", "--instance-ids", instance_id])
    reservations = desc.get("Reservations") or []
    instances: list[dict[str, Any]] = []
    for r in reservations:
        instances.extend(r.get("Instances") or [])
    if not instances:
        raise AwsCliError(f"Instance not found: {instance_id}")
    profile = (instances[0].get("IamInstanceProfile") or {}).get("Arn")
    if not profile:
        raise AwsCliError(
            f"Instance {instance_id} has no instance profile; "
            "cannot use awslogs safely."
        )
    # ARN format: arn:aws:iam::<acct>:instance-profile/<name>
    profile_name = str(profile).split("/")[-1]
    ip = _run_aws(
        ctx, ["iam", "get-instance-profile", "--instance-profile-name", profile_name]
    )
    roles = (ip.get("InstanceProfile") or {}).get("Roles") or []
    if not roles:
        raise AwsCliError(f"Instance profile has no roles: {profile_name}")
    return str(roles[0]["RoleName"])


def ensure_role_has_policy(ctx: AwsCtx, role_name: str, policy_arn: str) -> None:
    """
    Attach `policy_arn` to `role_name` if missing.

    This is the simplest least-effort gate for CloudWatch Logs permissions.
    """
    attached = _run_aws(
        ctx, ["iam", "list-attached-role-policies", "--role-name", role_name]
    )
    arns = {p["PolicyArn"] for p in attached.get("AttachedPolicies") or []}
    if policy_arn in arns:
        return
    _run_aws(
        ctx,
        [
            "iam",
            "attach-role-policy",
            "--role-name",
            role_name,
            "--policy-arn",
            policy_arn,
        ],
        expect_json=False,
    )


def ensure_log_group(ctx: AwsCtx, name: str) -> None:
    ok, msg = _try_run_aws(ctx, ["logs", "create-log-group", "--log-group-name", name])
    if ok:
        return
    # Idempotency: "ResourceAlreadyExistsException" is expected.
    if "ResourceAlreadyExistsException" in msg:
        return
    raise AwsCliError(f"Failed to create log group {name}: {msg}")


def ensure_retention(ctx: AwsCtx, name: str, days: int) -> None:
    _run_aws(
        ctx,
        [
            "logs",
            "put-retention-policy",
            "--log-group-name",
            name,
            "--retention-in-days",
            str(days),
        ],
        expect_json=False,
    )


def validate_log_group(ctx: AwsCtx, name: str, expected_days: int) -> None:
    out = _run_aws(
        ctx, ["logs", "describe-log-groups", "--log-group-name-prefix", name]
    )
    groups = out.get("logGroups") or []
    match = next((g for g in groups if g.get("logGroupName") == name), None)
    if not match:
        raise AwsCliError(f"Missing log group: {name}")
    days = match.get("retentionInDays")
    if int(days or 0) != int(expected_days):
        raise AwsCliError(
            f"Unexpected retention for {name}: {days} (expected {expected_days})"
        )


def validate_role_policy(ctx: AwsCtx, role_name: str, policy_arn: str) -> None:
    attached = _run_aws(
        ctx, ["iam", "list-attached-role-policies", "--role-name", role_name]
    )
    arns = {p["PolicyArn"] for p in attached.get("AttachedPolicies") or []}
    if policy_arn not in arns:
        raise AwsCliError(f"Role missing required policy: {role_name} -> {policy_arn}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis CloudWatch Logs baseline (I7)")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)
    p.add_argument("--policy-arn", default=DEFAULT_POLICY_ARN)
    p.add_argument("--dev-log-group", default="/auraxis/dev/containers")
    p.add_argument("--prod-log-group", default="/auraxis/prod/containers")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("apply", help="Create log groups + retention + attach IAM policy.")
    sub.add_parser("validate", help="Validate IAM policy + log groups retention.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)

    dev_role = _get_instance_role_name(ctx, args.dev_instance_id)
    prod_role = _get_instance_role_name(ctx, args.prod_instance_id)

    if args.cmd == "apply":
        ensure_role_has_policy(ctx, dev_role, args.policy_arn)
        ensure_role_has_policy(ctx, prod_role, args.policy_arn)

        ensure_log_group(ctx, args.dev_log_group)
        ensure_log_group(ctx, args.prod_log_group)

        ensure_retention(ctx, args.dev_log_group, DEV_RETENTION_DAYS)
        ensure_retention(ctx, args.prod_log_group, PROD_RETENTION_DAYS)
        return 0

    if args.cmd == "validate":
        validate_role_policy(ctx, dev_role, args.policy_arn)
        validate_role_policy(ctx, prod_role, args.policy_arn)
        validate_log_group(ctx, args.dev_log_group, DEV_RETENTION_DAYS)
        validate_log_group(ctx, args.prod_log_group, PROD_RETENTION_DAYS)
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
