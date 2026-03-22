#!/usr/bin/env python3
"""
Auraxis - S3 Backups (PostgreSQL) via SSM.

This script exists to implement a pragmatic, testable baseline for backups and
restore drills for a single-host Docker Compose deployment (PostgreSQL in a
container on an EC2 instance).

Goals
1. Create a dedicated S3 bucket with safe defaults:
   - Block public access
   - Default encryption (SSE-S3 AES256)
   - Bucket policy to enforce HTTPS + SSE on PUTs
   - Versioning enabled (best-effort safety net)
   - Lifecycle rules to control costs (expire by env prefix)
2. Grant least-privilege S3 access to the EC2 instance role (instance profile),
   via an inline policy (simple for a single-project lab account).
3. Run DB backups without SSH:
   - Execute `pg_dump` inside the postgres container
   - Compress on the host
   - Upload to S3
4. Validate restore capability:
   - Restore the latest DEV backup into a separate "drill" database
   - Non-destructive (does not touch the main DB)
5. Optionally schedule recurring backups via SSM Maintenance Window.

Notes (ops/infra)
- All instance-side actions use AWS Systems Manager (SSM). SSH is not required.
- This tool uses AWS CLI via subprocess; the operator authenticates locally
  using AWS SSO (recommended) or any other AWS CLI credentials method.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_BUCKET = "auraxis-backups-765480282720"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bddcfc8ea56c2ba3"

# This is the instance profile role we previously attached to DEV/PROD.
DEFAULT_EC2_ROLE_NAME = "auraxis-ec2-ssm-role"

# Maintenance window role created in earlier S1 steps (used by MW service).
DEFAULT_MAINTENANCE_WINDOW_ROLE_NAME = "auraxis-ssm-maintenance-window-role"

# Daily backups keep costs low while giving a reasonable restore point.
# AWS cron format: cron(Minutes Hours Day-of-month Month Day-of-week Year)
DEFAULT_DEV_BACKUP_CRON = "cron(15 4 * * ? *)"  # 04:15 UTC daily
DEFAULT_PROD_BACKUP_CRON = "cron(30 4 * * ? *)"  # 04:30 UTC daily


@dataclass(frozen=True)
class AwsCtx:
    """Immutable context for AWS CLI operations."""

    profile: str
    region: str


class AwsCliError(RuntimeError):
    """Raised when an `aws ...` CLI invocation fails."""

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


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_bucket(ctx: AwsCtx, bucket: str) -> None:
    # HeadBucket fails if missing or no permissions.
    try:
        _run_aws(ctx, ["s3api", "head-bucket", "--bucket", bucket], expect_json=False)
        exists = True
    except AwsCliError:
        exists = False

    if not exists:
        # us-east-1 has special create semantics (no LocationConstraint).
        if ctx.region == "us-east-1":
            _run_aws(
                ctx,
                ["s3api", "create-bucket", "--bucket", bucket],
                expect_json=False,
            )
        else:
            _run_aws(
                ctx,
                [
                    "s3api",
                    "create-bucket",
                    "--bucket",
                    bucket,
                    "--create-bucket-configuration",
                    json.dumps({"LocationConstraint": ctx.region}),
                ],
                expect_json=False,
            )

    # Safe defaults: block public access + encryption.
    _run_aws(
        ctx,
        [
            "s3api",
            "put-public-access-block",
            "--bucket",
            bucket,
            "--public-access-block-configuration",
            json.dumps(
                {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                }
            ),
        ],
        expect_json=False,
    )

    _run_aws(
        ctx,
        [
            "s3api",
            "put-bucket-encryption",
            "--bucket",
            bucket,
            "--server-side-encryption-configuration",
            json.dumps(
                {
                    "Rules": [
                        {
                            "ApplyServerSideEncryptionByDefault": {
                                "SSEAlgorithm": "AES256"
                            }
                        }
                    ]
                }
            ),
        ],
        expect_json=False,
    )

    # Versioning is a cheap safety net for accidental overwrites/deletes.
    _run_aws(
        ctx,
        [
            "s3api",
            "put-bucket-versioning",
            "--bucket",
            bucket,
            "--versioning-configuration",
            json.dumps({"Status": "Enabled"}),
        ],
        expect_json=False,
    )

    # Enforce HTTPS and SSE on writes.
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "DenyInsecureTransport",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:*",
                "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
            },
            {
                "Sid": "DenyUnencryptedObjectUploads",
                "Effect": "Deny",
                "Principal": "*",
                "Action": "s3:PutObject",
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
                "Condition": {
                    "StringNotEquals": {"s3:x-amz-server-side-encryption": "AES256"}
                },
            },
        ],
    }
    _run_aws(
        ctx,
        [
            "s3api",
            "put-bucket-policy",
            "--bucket",
            bucket,
            "--policy",
            json.dumps(bucket_policy),
        ],
        expect_json=False,
    )


def set_lifecycle(ctx: AwsCtx, bucket: str, *, prod_days: int, dev_days: int) -> None:
    # Expire objects by prefix; keeps costs under control.
    payload = {
        "Rules": [
            {
                "ID": "expire-prod",
                "Filter": {"Prefix": "prod/"},
                "Status": "Enabled",
                "Expiration": {"Days": prod_days},
            },
            {
                "ID": "expire-dev",
                "Filter": {"Prefix": "dev/"},
                "Status": "Enabled",
                "Expiration": {"Days": dev_days},
            },
            # Versioning enabled: ensure non-current versions are also cleaned.
            {
                "ID": "expire-noncurrent",
                "Filter": {},
                "Status": "Enabled",
                "NoncurrentVersionExpiration": {
                    "NoncurrentDays": max(prod_days, dev_days)
                },
            },
        ]
    }
    _run_aws(
        ctx,
        [
            "s3api",
            "put-bucket-lifecycle-configuration",
            "--bucket",
            bucket,
            "--lifecycle-configuration",
            json.dumps(payload),
        ],
        expect_json=False,
    )


def grant_ec2_role_access(ctx: AwsCtx, bucket: str, role_name: str) -> None:
    # Inline policy is simplest for a single-project lab account.
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowListBucket",
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
            {
                "Sid": "AllowReadWriteBackups",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            },
        ],
    }
    _run_aws(
        ctx,
        [
            "iam",
            "put-role-policy",
            "--role-name",
            role_name,
            "--policy-name",
            "auraxis-s3-backups-inline",
            "--policy-document",
            json.dumps(policy),
        ],
        expect_json=False,
    )


def _ssm_send(
    ctx: AwsCtx, instance_ids: list[str], commands: list[str], comment: str
) -> str:
    payload = json.dumps({"commands": commands})
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


def _ssm_get_command_output(
    ctx: AwsCtx, *, command_id: str, instance_id: str
) -> tuple[str, str, str]:
    """
    Fetch stdout/stderr/status for a specific SSM RunCommand invocation.

    Returns (status, stdout, stderr). Useful for verifying backup/restore without
    opening the AWS console.
    """
    out = _run_aws(
        ctx,
        [
            "ssm",
            "get-command-invocation",
            "--command-id",
            command_id,
            "--instance-id",
            instance_id,
        ],
        expect_json=True,
    )
    return (
        str(out.get("Status", "")),
        str(out.get("StandardOutputContent", "")),
        str(out.get("StandardErrorContent", "")),
    )


def _wrap_script_for_ssm_bash(script_lines: list[str]) -> list[str]:
    """
    Wrap a multi-line script into a single SSM `commands[]` entry.

    Why
    - On some systems/SSM versions, treating `commands[]` as separate invocations
      can break stateful steps (`cd`, exported vars, computed ids).
    - A single bash script keeps behavior deterministic across DEV/PROD and CI.
    """
    script = "\n".join(script_lines).rstrip() + "\n"
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    # Safe: base64 is alnum/+/, so single quotes are ok.
    return [
        (
            "TMP=/tmp/auraxis_ssm_script_$$.sh; "
            f"echo '{b64}' | base64 -d > \"$TMP\"; "
            'bash "$TMP"; RC=$?; rm -f "$TMP"; exit $RC'
        )
    ]


def install_awscli_on_instances(ctx: AwsCtx, instance_ids: list[str]) -> str:
    script_lines = [
        "set -eu",
        _ensure_awscli_shell(),
        "aws --version || true",
    ]
    commands = _wrap_script_for_ssm_bash(script_lines)
    return _ssm_send(ctx, instance_ids, commands, "auraxis: install awscli for backups")


def _ensure_awscli_shell() -> str:
    """
    Return a shell snippet to ensure AWS CLI is installed on the host.

    Rationale
    - Some Ubuntu images do not have `awscli` available via apt repos without
      additional setup. We first attempt apt (cheap) and fall back to the
      official AWS CLI v2 installer (reliable).
    """
    # NOTE: keep it POSIX-ish for AWS-RunShellScript.
    return (
        "if command -v aws >/dev/null 2>&1; then "
        "echo 'awscli already installed'; "
        "else "
        "sudo apt-get update -y >/dev/null 2>&1 || true; "
        "sudo apt-get install -y awscli >/dev/null 2>&1 || true; "
        "if ! command -v aws >/dev/null 2>&1; then "
        "TMPDIR=$(mktemp -d); "
        'cd "$TMPDIR"; '
        "sudo apt-get install -y unzip >/dev/null 2>&1 || true; "
        "curl -fsSL "
        "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip "
        "-o awscliv2.zip; "
        "unzip -q awscliv2.zip; "
        "sudo ./aws/install --update; "
        'cd /; rm -rf "$TMPDIR"; '
        "fi; "
        "fi"
    )


def _pick_workdir_shell() -> str:
    """
    Returns a POSIX shell snippet to choose the correct working directory.

    We historically used different paths on PROD vs DEV. This keeps the backup
    commands compatible without requiring any manual rename/migration.
    """
    return (
        'if [ -d "/opt/auraxis" ]; then cd /opt/auraxis; '
        'elif [ -d "/opt/flask_expenses" ]; then cd /opt/flask_expenses; '
        "else echo 'No workdir found under /opt' >&2; exit 2; fi"
    )


def run_backup(
    ctx: AwsCtx,
    *,
    env_name: str,
    instance_id: str,
    bucket: str,
    compose_file: str,
    env_file: str,
) -> str:
    ts = _utc_ts()
    key = f"{env_name}/{instance_id}/{ts}.sql.gz"
    s3_uri = f"s3://{bucket}/{key}"

    # This runs on the instance. It expects docker compose + postgres container running.
    # We use docker compose to locate the DB container id (no hardcoded names).
    script_lines = [
        "set -eu",
        # Ensure we run under the compose directory (do not rely on SSM command state).
        _pick_workdir_shell(),
        "sudo apt-get update -y >/dev/null 2>&1 || true",
        _ensure_awscli_shell(),
        (
            "DB_CID=$(docker compose --env-file {env_file} -f {compose_file} ps -q db)"
        ).format(env_file=env_file, compose_file=compose_file),
        'test -n "$DB_CID"',
        # Extract creds from env file (avoid leaking to logs). Assumes KEY=VALUE lines.
        (
            "export POSTGRES_USER=$(grep -E '^POSTGRES_USER=' {env_file} "
            "| cut -d= -f2-)"
        ).format(env_file=env_file),
        (
            "export POSTGRES_DB=$(grep -E '^POSTGRES_DB=' {env_file} | cut -d= -f2-)"
        ).format(env_file=env_file),
        f"OUT=/tmp/auraxis_backup_{env_name}_{ts}.sql.gz",
        'echo "creating backup: $OUT"',
        # Run pg_dump inside the db container and compress on the host.
        (
            'docker exec "$DB_CID" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" '
            '| gzip -c > "$OUT"'
        ),
        # Bucket policy enforces SSE header even with default encryption enabled.
        f'aws s3 cp "$OUT" "{s3_uri}" --sse AES256',
        'rm -f "$OUT"',
        f'echo "uploaded: {s3_uri}"',
    ]
    commands = _wrap_script_for_ssm_bash(script_lines)
    return _ssm_send(
        ctx, [instance_id], commands, f"auraxis: {env_name} postgres backup to s3"
    )


def restore_drill_dev(
    ctx: AwsCtx,
    *,
    dev_instance_id: str,
    bucket: str,
    compose_file: str,
    env_file: str,
    restore_db: str = "auraxis_restore_drill",
) -> str:
    # Restore latest DEV backup into a separate DB inside the DEV postgres container.
    # This is a non-destructive drill that validates we can restore.
    script_lines = [
        "set -eu",
        _pick_workdir_shell(),
        _ensure_awscli_shell(),
        (
            "DB_CID=$(docker compose --env-file {env_file} -f {compose_file} ps -q db)"
        ).format(env_file=env_file, compose_file=compose_file),
        'test -n "$DB_CID"',
        (
            "export POSTGRES_USER=$(grep -E '^POSTGRES_USER=' {env_file} "
            "| cut -d= -f2-)"
        ).format(env_file=env_file),
        (
            "LATEST=$(aws s3api list-objects-v2 --bucket {bucket} "
            "--prefix dev/{iid}/ "
            "--query 'sort_by(Contents,&LastModified)[-1].Key' --output text)"
        ).format(bucket=bucket, iid=dev_instance_id),
        'test "$LATEST" != "None"',
        "TMP=/tmp/auraxis_restore_drill.sql.gz",
        'aws s3 cp "s3://{bucket}/$LATEST" "$TMP"'.format(bucket=bucket),
        # Recreate drill DB.
        (
            f'docker exec "$DB_CID" psql -U "$POSTGRES_USER" -d postgres -c '
            f'"DROP DATABASE IF EXISTS {restore_db};"'
        ),
        (
            f'docker exec "$DB_CID" psql -U "$POSTGRES_USER" -d postgres -c '
            f'"CREATE DATABASE {restore_db};"'
        ),
        (
            f'gunzip -c "$TMP" | docker exec -i "$DB_CID" psql -U "$POSTGRES_USER" '
            f"-d {restore_db}"
        ),
        'rm -f "$TMP"',
        f'echo "restore drill completed into db={restore_db} from $LATEST"',
    ]
    commands = _wrap_script_for_ssm_bash(script_lines)
    return _ssm_send(ctx, [dev_instance_id], commands, "auraxis: restore drill (dev)")


def _ensure_maintenance_window(
    ctx: AwsCtx,
    *,
    name: str,
    schedule: str,
    duration_hours: int = 2,
    cutoff_hours: int = 1,
) -> str:
    """
    Ensure an SSM Maintenance Window exists and return its WindowId.

    We keep MW creation idempotent by listing by name first.
    """
    out = _run_aws(
        ctx,
        [
            "ssm",
            "describe-maintenance-windows",
            "--filters",
            f"Key=Name,Values={name}",
        ],
        expect_json=True,
    )
    wins = out.get("WindowIdentities") or []
    if wins:
        return str(wins[0]["WindowId"])

    created = _run_aws(
        ctx,
        [
            "ssm",
            "create-maintenance-window",
            "--name",
            name,
            "--schedule",
            schedule,
            "--duration",
            str(duration_hours),
            "--cutoff",
            str(cutoff_hours),
            "--allow-unassociated-targets",
        ],
        expect_json=True,
    )
    return str(created["WindowId"])


def _ensure_mw_target(
    ctx: AwsCtx, *, window_id: str, name: str, app: str, environment: str
) -> str:
    """
    Ensure a Maintenance Window target exists (by tag selector) and return its TargetId.
    """
    existing = _run_aws(
        ctx,
        ["ssm", "describe-maintenance-window-targets", "--window-id", window_id],
        expect_json=True,
    )
    for t in existing.get("Targets") or []:
        if t.get("Name") == name:
            return str(t["WindowTargetId"])

    created = _run_aws(
        ctx,
        [
            "ssm",
            "register-target-with-maintenance-window",
            "--window-id",
            window_id,
            "--resource-type",
            "INSTANCE",
            "--name",
            name,
            "--targets",
            f"Key=tag:App,Values={app}",
            f"Key=tag:Environment,Values={environment}",
        ],
        expect_json=True,
    )
    return str(created["WindowTargetId"])


def _get_role_arn(ctx: AwsCtx, role_name: str) -> str:
    out = _run_aws(ctx, ["iam", "get-role", "--role-name", role_name], expect_json=True)
    return str(out["Role"]["Arn"])


def _ensure_mw_task(
    ctx: AwsCtx,
    *,
    window_id: str,
    name: str,
    window_target_id: str,
    service_role_arn: str,
    commands: list[str],
    max_concurrency: str = "1",
    max_errors: str = "1",
    force_update: bool = False,
) -> str:
    """
    Ensure a Maintenance Window task exists and return its WindowTaskId.

    We identify tasks by their Name field.
    """
    existing = _run_aws(
        ctx, ["ssm", "describe-maintenance-window-tasks", "--window-id", window_id]
    )
    for t in existing.get("Tasks") or []:
        if t.get("Name") == name:
            task_id = str(t["WindowTaskId"])
            if not force_update:
                return task_id
            _run_aws(
                ctx,
                [
                    "ssm",
                    "deregister-task-from-maintenance-window",
                    "--window-id",
                    window_id,
                    "--window-task-id",
                    task_id,
                ],
                expect_json=False,
            )
            break

    invocation = {
        "RunCommand": {
            "Parameters": {"commands": commands},
            "TimeoutSeconds": 3600,
        }
    }
    created = _run_aws(
        ctx,
        [
            "ssm",
            "register-task-with-maintenance-window",
            "--window-id",
            window_id,
            "--name",
            name,
            "--task-arn",
            "AWS-RunShellScript",
            "--task-type",
            "RUN_COMMAND",
            "--targets",
            f"Key=WindowTargetIds,Values={window_target_id}",
            "--service-role-arn",
            service_role_arn,
            "--task-invocation-parameters",
            json.dumps(invocation),
            "--max-concurrency",
            max_concurrency,
            "--max-errors",
            max_errors,
            "--priority",
            "1",
        ],
        expect_json=True,
    )
    return str(created["WindowTaskId"])


def schedule_backups_via_ssm_mw(
    ctx: AwsCtx,
    *,
    bucket: str,
    mw_role_name: str,
    dev_schedule: str,
    prod_schedule: str,
    compose_file: str,
    env_file: str,
    force_update: bool = False,
) -> dict[str, str]:
    """
    Create (or reuse) maintenance windows for DEV and PROD backups.

    Backups run on the instances and upload to S3 using the instance role.
    """
    role_arn = _get_role_arn(ctx, mw_role_name)

    dev_win = _ensure_maintenance_window(
        ctx, name="auraxis-dev-backups", schedule=dev_schedule
    )
    prod_win = _ensure_maintenance_window(
        ctx, name="auraxis-prod-backups", schedule=prod_schedule
    )

    dev_tgt = _ensure_mw_target(
        ctx,
        window_id=dev_win,
        name="auraxis-dev-backups-target",
        app="auraxis",
        environment="dev",
    )
    prod_tgt = _ensure_mw_target(
        ctx,
        window_id=prod_win,
        name="auraxis-prod-backups-target",
        app="auraxis",
        environment="prod",
    )

    # Task commands (run on each instance that matches the target tags).
    # We avoid hardcoding paths by auto-detecting the workdir.
    common_cmds = [
        "set -eu",
        _pick_workdir_shell(),
        "sudo apt-get update -y >/dev/null 2>&1 || true",
        _ensure_awscli_shell(),
        f"DB_CID=$(docker compose --env-file {env_file} -f {compose_file} ps -q db)",
        'test -n "$DB_CID"',
        (
            f"export POSTGRES_USER=$(grep -E '^POSTGRES_USER=' {env_file} "
            "| cut -d= -f2-)"
        ),
        (f"export POSTGRES_DB=$(grep -E '^POSTGRES_DB=' {env_file} | cut -d= -f2-)"),
    ]

    def mk_backup_cmds(env_name: str) -> list[str]:
        # NOTE: MW executions happen later; we compute timestamp at runtime instead.
        # Keeping the Python-side prefix consistent is the important part.
        script_lines = [
            *common_cmds,
            'TS="$(date -u +%Y%m%dT%H%M%SZ)"',
            # IMDSv2 is enforced; obtain a token before fetching instance-id.
            'IMDS_TOKEN="$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" '
            '-H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)"',
            'IID="$(curl -sS --max-time 2 -H "X-aws-ec2-metadata-token: $IMDS_TOKEN" '
            'http://169.254.169.254/latest/meta-data/instance-id)"',
            f'OUT="/tmp/auraxis_backup_{env_name}_$TS.sql.gz"',
            'echo "creating backup: $OUT"',
            (
                'docker exec "$DB_CID" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" '
                '| gzip -c > "$OUT"'
            ),
            (
                f'aws s3 cp "$OUT" "s3://{bucket}/{env_name}/$IID/$TS.sql.gz" '
                "--sse AES256"
            ),
            'rm -f "$OUT"',
            'echo "backup uploaded"',
        ]
        return _wrap_script_for_ssm_bash(script_lines)

    dev_task = _ensure_mw_task(
        ctx,
        window_id=dev_win,
        name="auraxis-dev-backup-task",
        window_target_id=dev_tgt,
        service_role_arn=role_arn,
        commands=mk_backup_cmds("dev"),
        force_update=force_update,
    )
    prod_task = _ensure_mw_task(
        ctx,
        window_id=prod_win,
        name="auraxis-prod-backup-task",
        window_target_id=prod_tgt,
        service_role_arn=role_arn,
        commands=mk_backup_cmds("prod"),
        force_update=force_update,
    )

    return {
        "dev_window_id": dev_win,
        "dev_task_id": dev_task,
        "prod_window_id": prod_win,
        "prod_task_id": prod_task,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis S3 backups via SSM")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--ec2-role-name", default=DEFAULT_EC2_ROLE_NAME)
    p.add_argument("--mw-role-name", default=DEFAULT_MAINTENANCE_WINDOW_ROLE_NAME)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)
    p.add_argument("--compose-file", default="docker-compose.prod.yml")
    p.add_argument("--env-file", default=".env.prod")
    p.add_argument(
        "--prod-retention-days",
        type=int,
        default=30,
        help="Retention (days) for PROD backups (prefix prod/).",
    )
    p.add_argument(
        "--dev-retention-days",
        type=int,
        default=7,
        help="Retention (days) for DEV backups (prefix dev/).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser(
        "setup", help="Create bucket, lifecycle and IAM access for EC2 role."
    )
    sub.add_parser("install-awscli", help="Install awscli on DEV/PROD via SSM.")
    sub.add_parser("backup-prod", help="Run PROD backup now.")
    sub.add_parser("backup-dev", help="Run DEV backup now.")
    sub.add_parser(
        "restore-drill-dev", help="Restore latest DEV backup into a drill DB."
    )
    p_sched = sub.add_parser(
        "schedule-backups",
        help="Create or reuse SSM Maintenance Windows for daily DEV/PROD backups.",
    )
    p_sched.add_argument("--dev-cron", default=DEFAULT_DEV_BACKUP_CRON)
    p_sched.add_argument("--prod-cron", default=DEFAULT_PROD_BACKUP_CRON)
    p_sched.add_argument(
        "--force-update",
        action="store_true",
        help="If set, deregister and re-register tasks to update command payloads.",
    )
    p_out = sub.add_parser(
        "ssm-output",
        help="Fetch stdout/stderr/status for an SSM command id (debug / verification).",
    )
    p_out.add_argument("--command-id", required=True)
    p_out.add_argument("--instance-id", required=True)
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)

    if args.cmd == "setup":
        ensure_bucket(ctx, args.bucket)
        set_lifecycle(
            ctx,
            args.bucket,
            prod_days=args.prod_retention_days,
            dev_days=args.dev_retention_days,
        )
        grant_ec2_role_access(ctx, args.bucket, args.ec2_role_name)
        print("setup complete")
        return 0

    if args.cmd == "install-awscli":
        cmd_id = install_awscli_on_instances(
            ctx, [args.prod_instance_id, args.dev_instance_id]
        )
        print(cmd_id)
        return 0

    if args.cmd == "backup-prod":
        cmd_id = run_backup(
            ctx,
            env_name="prod",
            instance_id=args.prod_instance_id,
            bucket=args.bucket,
            compose_file=args.compose_file,
            env_file=args.env_file,
        )
        print(cmd_id)
        return 0

    if args.cmd == "backup-dev":
        cmd_id = run_backup(
            ctx,
            env_name="dev",
            instance_id=args.dev_instance_id,
            bucket=args.bucket,
            compose_file=args.compose_file,
            env_file=args.env_file,
        )
        print(cmd_id)
        return 0

    if args.cmd == "restore-drill-dev":
        cmd_id = restore_drill_dev(
            ctx,
            dev_instance_id=args.dev_instance_id,
            bucket=args.bucket,
            compose_file=args.compose_file,
            env_file=args.env_file,
        )
        print(cmd_id)
        return 0

    if args.cmd == "schedule-backups":
        out = schedule_backups_via_ssm_mw(
            ctx,
            bucket=args.bucket,
            mw_role_name=args.mw_role_name,
            dev_schedule=args.dev_cron,
            prod_schedule=args.prod_cron,
            compose_file=args.compose_file,
            env_file=args.env_file,
            force_update=bool(args.force_update),
        )
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    if args.cmd == "ssm-output":
        status, stdout, stderr = _ssm_get_command_output(
            ctx, command_id=args.command_id, instance_id=args.instance_id
        )
        print(f"Status: {status}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}")
        return 0

    print("unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
