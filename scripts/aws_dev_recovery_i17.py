#!/usr/bin/env python3
"""
Auraxis - DEV host recovery / replacement baseline (I17).

Goal
- turn DEV host replacement into a reproducible, auditable, SSM-based procedure
- keep AWS SSM Parameter Store as the canonical source of truth for runtime secrets
- reduce dependence on the old host filesystem state
"""

from __future__ import annotations

import argparse
import base64
import importlib
import json
import subprocess
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

try:
    runtime_defaults = importlib.import_module("scripts.aws_runtime_defaults")
except ImportError:
    runtime_defaults = importlib.import_module("aws_runtime_defaults")


@dataclass(frozen=True)
class AwsCtx:
    profile: str
    region: str


@dataclass(frozen=True)
class InstanceLaunchPlan:
    source_instance_id: str
    source_name: str
    replacement_name: str
    image_id: str
    instance_type: str
    subnet_id: str
    security_group_ids: tuple[str, ...]
    iam_instance_profile_name: str | None
    key_name: str | None
    elastic_ip_allocation_id: str
    elastic_ip_public_ip: str
    domain: str
    ssm_path: str
    git_ref: str

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


class AwsCliError(RuntimeError):
    pass


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
    payload = (process.stdout or "").strip()
    if not payload:
        return {}
    return json.loads(payload)


def _require_str(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AwsCliError(f"Missing required field '{key}' in AWS payload.")
    return value


def _ssm_send_shell(ctx: AwsCtx, instance_id: str, script: str, comment: str) -> str:
    b64 = base64.b64encode(script.encode("utf-8")).decode("ascii")
    command = (
        "TMP=/tmp/auraxis_ssm_dev_recovery_i17_$$.sh; "
        f"echo '{b64}' | base64 -d > \"$TMP\"; "
        'bash "$TMP"; RC=$?; rm -f "$TMP"; exit $RC'
    )
    payload = json.dumps({"commands": [command]})
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
    if not isinstance(out, dict):
        raise AwsCliError("Unexpected SSM send-command response.")
    command_dict = cast(dict[str, Any], out.get("Command") or {})
    return _require_str(command_dict, "CommandId")


def _wait_for_ssm_command(ctx: AwsCtx, *, command_id: str, instance_id: str) -> None:
    deadline = time.time() + 1800
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
        if not isinstance(out, dict):
            raise AwsCliError("Unexpected SSM invocation response.")
        status = str(out.get("Status") or "Unknown")
        if status in {"Pending", "InProgress", "Delayed"}:
            time.sleep(5)
            continue
        if status != "Success":
            stdout = str(out.get("StandardOutputContent") or "").strip()
            stderr = str(out.get("StandardErrorContent") or "").strip()
            raise AwsCliError(
                "SSM command failed "
                f"status={status}\nSTDOUT:\n{stdout[-8000:]}\nSTDERR:\n{stderr[-8000:]}"
            )
        return
    raise AwsCliError(
        "Timeout waiting for SSM command completion. "
        f"instance_id={instance_id} command_id={command_id}"
    )


def _wait_for_instance_state(
    ctx: AwsCtx, *, instance_id: str, waiter_name: str, delay: int = 15
) -> None:
    args = [
        "ec2",
        "wait",
        waiter_name,
        "--instance-ids",
        instance_id,
        "--cli-read-timeout",
        "60",
        "--cli-connect-timeout",
        "30",
    ]
    _run_aws(ctx, args, expect_json=False)
    time.sleep(delay)


def _wait_for_ssm_online(ctx: AwsCtx, *, instance_id: str) -> None:
    deadline = time.time() + 1200
    while time.time() < deadline:
        out = _run_aws(
            ctx,
            [
                "ssm",
                "describe-instance-information",
                "--filters",
                f"Key=InstanceIds,Values={instance_id}",
            ],
        )
        if not isinstance(out, dict):
            raise AwsCliError("Unexpected SSM instance-information response.")
        info_list = out.get("InstanceInformationList") or []
        if not isinstance(info_list, list):
            raise AwsCliError("Unexpected SSM instance-information format.")
        for info in info_list:
            if not isinstance(info, dict):
                continue
            if str(info.get("PingStatus") or "") == "Online":
                return
        time.sleep(10)
    raise AwsCliError(f"SSM agent did not become Online for instance {instance_id}.")


def _describe_instance(ctx: AwsCtx, instance_id: str) -> dict[str, Any]:
    out = _run_aws(ctx, ["ec2", "describe-instances", "--instance-ids", instance_id])
    if not isinstance(out, dict):
        raise AwsCliError("Unexpected describe-instances response.")
    reservations = out.get("Reservations") or []
    if not isinstance(reservations, list) or not reservations:
        raise AwsCliError(f"Instance not found: {instance_id}")
    for reservation in reservations:
        if not isinstance(reservation, dict):
            continue
        instances = reservation.get("Instances") or []
        if not isinstance(instances, list) or not instances:
            continue
        instance = instances[0]
        if isinstance(instance, dict):
            return cast(dict[str, Any], instance)
    raise AwsCliError(f"Instance payload missing details: {instance_id}")


def _extract_tag_name(instance: dict[str, Any]) -> str:
    tags = instance.get("Tags") or []
    if not isinstance(tags, list):
        return ""
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        if str(tag.get("Key") or "") == "Name":
            return str(tag.get("Value") or "")
    return ""


def _find_eip_for_instance(ctx: AwsCtx, instance_id: str) -> dict[str, Any]:
    out = _run_aws(
        ctx,
        [
            "ec2",
            "describe-addresses",
            "--filters",
            f"Name=instance-id,Values={instance_id}",
        ],
    )
    if not isinstance(out, dict):
        raise AwsCliError("Unexpected describe-addresses response.")
    addresses = out.get("Addresses") or []
    if not isinstance(addresses, list) or not addresses:
        raise AwsCliError(
            f"No Elastic IP associated with source instance. instance_id={instance_id}"
        )
    address = addresses[0]
    if not isinstance(address, dict):
        raise AwsCliError("Unexpected EIP payload.")
    return cast(dict[str, Any], address)


def _instance_profile_name(instance: dict[str, Any]) -> str | None:
    profile = instance.get("IamInstanceProfile")
    if not isinstance(profile, dict):
        return None
    arn = profile.get("Arn")
    if not isinstance(arn, str) or "/" not in arn:
        return None
    return arn.rsplit("/", 1)[-1]


def build_replacement_plan(
    *,
    source_instance: dict[str, Any],
    elastic_ip: dict[str, Any],
    replacement_name: str,
    git_ref: str,
    domain: str,
    ssm_path: str,
    ami_id_override: str | None = None,
    instance_type_override: str | None = None,
    subnet_id_override: str | None = None,
    security_group_ids_override: tuple[str, ...] | None = None,
    iam_instance_profile_name_override: str | None = None,
    key_name_override: str | None = None,
) -> InstanceLaunchPlan:
    security_groups = source_instance.get("SecurityGroups") or []
    if not isinstance(security_groups, list) or not security_groups:
        raise AwsCliError("Source instance has no security groups.")
    source_security_group_ids = tuple(
        _require_str(cast(dict[str, Any], group), "GroupId")
        for group in security_groups
        if isinstance(group, dict)
    )
    if not source_security_group_ids:
        raise AwsCliError("Source instance has no valid security group ids.")

    source_name = _extract_tag_name(source_instance) or _require_str(
        source_instance, "InstanceId"
    )
    allocation_id = _require_str(elastic_ip, "AllocationId")
    public_ip = _require_str(elastic_ip, "PublicIp")

    return InstanceLaunchPlan(
        source_instance_id=_require_str(source_instance, "InstanceId"),
        source_name=source_name,
        replacement_name=replacement_name,
        image_id=ami_id_override or _require_str(source_instance, "ImageId"),
        instance_type=instance_type_override
        or _require_str(source_instance, "InstanceType"),
        subnet_id=subnet_id_override or _require_str(source_instance, "SubnetId"),
        security_group_ids=security_group_ids_override or source_security_group_ids,
        iam_instance_profile_name=(
            iam_instance_profile_name_override
            or _instance_profile_name(source_instance)
        ),
        key_name=key_name_override or cast(str | None, source_instance.get("KeyName")),
        elastic_ip_allocation_id=allocation_id,
        elastic_ip_public_ip=public_ip,
        domain=domain,
        ssm_path=ssm_path,
        git_ref=git_ref,
    )


def _build_bootstrap_script(plan: InstanceLaunchPlan, *, aws_region: str) -> str:
    override_items = [
        "AURAXIS_ENV=dev",
        f"AWS_REGION={aws_region}",
        "AURAXIS_SECRETS_BACKEND=ssm",
        f"AURAXIS_SSM_PATH={plan.ssm_path}",
        f"DOMAIN={plan.domain}",
        "CERTBOT_EMAIL=",
        "EDGE_TLS_MODE=instance_tls",
        "DOCS_EXPOSURE_POLICY=disabled",
        "SENTRY_ENVIRONMENT=dev",
        "CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173",
    ]
    override_args = " ".join(f"--set {json.dumps(item)}" for item in override_items)
    repo_url = json.dumps(runtime_defaults.DEFAULT_PUBLIC_REPO_URL)
    git_ref = json.dumps(plan.git_ref)
    ssm_path = json.dumps(plan.ssm_path)
    domain = json.dumps(plan.domain)
    aws_region_arg = json.dumps(aws_region)

    return f"""\
set -euo pipefail

OP_USER="ubuntu"
if [ ! -d "/home/$OP_USER" ]; then
  OP_USER="$(id -un)"
fi

sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \\
  ca-certificates curl git jq python3 python3-venv docker.io docker-compose-plugin

sudo systemctl enable docker
sudo systemctl restart docker
sudo usermod -aG docker "$OP_USER" || true

sudo mkdir -p /opt
if [ ! -d /opt/auraxis/.git ]; then
  sudo git clone {repo_url} /opt/auraxis
fi

sudo chown -R "$OP_USER:$OP_USER" /opt/auraxis
sudo ln -sfn /opt/auraxis /opt/flask_expenses

sudo -u "$OP_USER" git -C /opt/auraxis remote set-url origin {repo_url}
sudo -u "$OP_USER" git -C /opt/auraxis fetch --all --prune
sudo -u "$OP_USER" git -C /opt/auraxis checkout -f {git_ref}
sudo -u "$OP_USER" git -C /opt/auraxis reset --hard {git_ref}

cd /opt/auraxis
python3 scripts/sync_cloud_secrets.py \\
  --backend ssm \\
  --region {aws_region_arg} \\
  --ssm-path {ssm_path} \\
  --base-env .env.prod.example \\
  --output .env.prod \\
  {override_args}

chmod 600 .env.prod
docker compose --env-file .env.prod -f docker-compose.prod.yml config >/dev/null
echo "[i17] bootstrap complete domain={domain}"
"""


def _launch_instance(ctx: AwsCtx, plan: InstanceLaunchPlan) -> str:
    tag_specifications = json.dumps(
        [
            {
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": plan.replacement_name},
                    {"Key": "Environment", "Value": "dev"},
                    {"Key": "ManagedBy", "Value": "auraxis-api-ops-12"},
                    {"Key": "SourceInstanceId", "Value": plan.source_instance_id},
                ],
            }
        ]
    )
    args = [
        "ec2",
        "run-instances",
        "--image-id",
        plan.image_id,
        "--instance-type",
        plan.instance_type,
        "--subnet-id",
        plan.subnet_id,
        "--security-group-ids",
        *list(plan.security_group_ids),
        "--tag-specifications",
        tag_specifications,
        "--count",
        "1",
    ]
    if plan.iam_instance_profile_name:
        args.extend(
            [
                "--iam-instance-profile",
                f"Name={plan.iam_instance_profile_name}",
            ]
        )
    if plan.key_name:
        args.extend(["--key-name", plan.key_name])

    out = _run_aws(ctx, args)
    if not isinstance(out, dict):
        raise AwsCliError("Unexpected run-instances response.")
    instances = out.get("Instances") or []
    if not isinstance(instances, list) or not instances:
        raise AwsCliError("EC2 did not return the launched instance.")
    first = instances[0]
    if not isinstance(first, dict):
        raise AwsCliError("Unexpected instance payload from run-instances.")
    return _require_str(first, "InstanceId")


def _validate_local_health(ctx: AwsCtx, *, instance_id: str) -> None:
    script = """\
set -euo pipefail
curl -fsS http://127.0.0.1/healthz >/dev/null
echo "[i17] local health ok"
"""
    command_id = _ssm_send_shell(
        ctx, instance_id, script, "auraxis: i17 validate local health"
    )
    _wait_for_ssm_command(ctx, command_id=command_id, instance_id=instance_id)


def _validate_public_health(
    *, scheme: str, domain: str, timeout_seconds: int = 120
) -> None:
    url = f"{scheme}://{domain}/healthz"
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=8) as response:
                if int(response.status) == 200:
                    return
                last_error = f"unexpected status={response.status}"
        except Exception as exc:  # pragma: no cover - network exercised in ops only
            last_error = str(exc)
        time.sleep(5)
    raise AwsCliError(f"Public health check failed for {url}: {last_error}")


def _run_deploy_helper(
    ctx: AwsCtx,
    *,
    instance_id: str,
    git_ref: str,
) -> None:
    helper_path = Path(__file__).with_name("aws_deploy_i6.py")
    cmd = [
        "python3",
        str(helper_path),
        "--profile",
        ctx.profile,
        "--region",
        ctx.region,
        "--dev-instance-id",
        instance_id,
        "deploy",
        "--env",
        "dev",
        "--git-ref",
        git_ref,
    ]
    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if process.returncode != 0:
        raise AwsCliError(
            "Deploy helper failed for replacement DEV host.\n"
            f"STDOUT:\n{process.stdout[-8000:]}\nSTDERR:\n{process.stderr[-8000:]}"
        )


def _rename_source_instance(
    ctx: AwsCtx, *, source_instance_id: str, replacement_name: str
) -> None:
    tag_value = f"{replacement_name}_replaced"
    _run_aws(
        ctx,
        [
            "ec2",
            "create-tags",
            "--resources",
            source_instance_id,
            "--tags",
            f"Key=Name,Value={tag_value}",
        ],
        expect_json=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auraxis DEV host replacement baseline (I17)."
    )
    parser.add_argument("--profile", default=runtime_defaults.DEFAULT_PROFILE)
    parser.add_argument("--region", default=runtime_defaults.DEFAULT_REGION)

    sub = parser.add_subparsers(dest="cmd", required=True)

    status = sub.add_parser("status", help="Show current DEV baseline and EIP.")
    status.add_argument(
        "--source-instance-id", default=runtime_defaults.DEFAULT_DEV_INSTANCE_ID
    )

    replace = sub.add_parser(
        "replace",
        help="Launch, bootstrap and optionally cut over a replacement DEV host.",
    )
    replace.add_argument(
        "--source-instance-id", default=runtime_defaults.DEFAULT_DEV_INSTANCE_ID
    )
    replace.add_argument("--git-ref", default="origin/master")
    replace.add_argument("--replacement-name", default="")
    replace.add_argument("--ami-id", default="")
    replace.add_argument("--instance-type", default="")
    replace.add_argument("--subnet-id", default="")
    replace.add_argument(
        "--security-group-id",
        dest="security_group_ids",
        action="append",
        default=[],
    )
    replace.add_argument("--iam-instance-profile-name", default="")
    replace.add_argument("--key-name", default="")
    replace.add_argument("--cutover-eip", action="store_true")
    replace.add_argument("--stop-source", action="store_true")
    replace.add_argument(
        "--execute",
        action="store_true",
        help="Perform the replacement. Without this flag, only prints the plan.",
    )
    return parser


def _replacement_name_from_source(source_name: str) -> str:
    suffix = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    return f"{source_name}-replacement-{suffix}"


def _security_group_ids(raw_ids: list[str]) -> tuple[str, ...] | None:
    cleaned = tuple(item.strip() for item in raw_ids if item.strip())
    return cleaned or None


def _plan_from_args(args: argparse.Namespace, ctx: AwsCtx) -> InstanceLaunchPlan:
    source_instance_id = str(args.source_instance_id)
    source_instance = _describe_instance(ctx, source_instance_id)
    elastic_ip = _find_eip_for_instance(ctx, source_instance_id)
    source_name = _extract_tag_name(source_instance) or source_instance_id
    replacement_name = str(
        args.replacement_name
    ).strip() or _replacement_name_from_source(source_name)
    return build_replacement_plan(
        source_instance=source_instance,
        elastic_ip=elastic_ip,
        replacement_name=replacement_name,
        git_ref=str(args.git_ref),
        domain=runtime_defaults.DEFAULT_DEV_DOMAIN,
        ssm_path=runtime_defaults.DEFAULT_DEV_SSM_PATH,
        ami_id_override=str(args.ami_id).strip() or None,
        instance_type_override=str(args.instance_type).strip() or None,
        subnet_id_override=str(args.subnet_id).strip() or None,
        security_group_ids_override=_security_group_ids(list(args.security_group_ids)),
        iam_instance_profile_name_override=(
            str(args.iam_instance_profile_name).strip() or None
        ),
        key_name_override=str(args.key_name).strip() or None,
    )


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)

    if args.cmd == "status":
        plan = _plan_from_args(
            argparse.Namespace(
                source_instance_id=args.source_instance_id,
                replacement_name="",
                git_ref="origin/master",
                ami_id="",
                instance_type="",
                subnet_id="",
                security_group_ids=[],
                iam_instance_profile_name="",
                key_name="",
            ),
            ctx,
        )
        print(json.dumps(plan.to_json_dict(), indent=2, sort_keys=True))
        return 0

    if args.cmd == "replace":
        plan = _plan_from_args(args, ctx)
        print(json.dumps(plan.to_json_dict(), indent=2, sort_keys=True))
        if not args.execute:
            print("Dry-run only. Re-run with --execute to apply.")
            return 0

        replacement_instance_id = _launch_instance(ctx, plan)
        print(f"[i17] launched replacement instance: {replacement_instance_id}")
        _wait_for_instance_state(
            ctx, instance_id=replacement_instance_id, waiter_name="instance-running"
        )
        _wait_for_instance_state(
            ctx, instance_id=replacement_instance_id, waiter_name="instance-status-ok"
        )
        _wait_for_ssm_online(ctx, instance_id=replacement_instance_id)

        bootstrap_script = _build_bootstrap_script(plan, aws_region=ctx.region)
        bootstrap_command_id = _ssm_send_shell(
            ctx,
            replacement_instance_id,
            bootstrap_script,
            "auraxis: i17 bootstrap replacement dev host",
        )
        _wait_for_ssm_command(
            ctx, command_id=bootstrap_command_id, instance_id=replacement_instance_id
        )

        _run_deploy_helper(
            ctx,
            instance_id=replacement_instance_id,
            git_ref=plan.git_ref,
        )
        _validate_local_health(ctx, instance_id=replacement_instance_id)

        if args.cutover_eip:
            _run_aws(
                ctx,
                [
                    "ec2",
                    "associate-address",
                    "--allocation-id",
                    plan.elastic_ip_allocation_id,
                    "--instance-id",
                    replacement_instance_id,
                    "--allow-reassociation",
                ],
                expect_json=False,
            )
            _validate_public_health(scheme="http", domain=plan.domain)
            _rename_source_instance(
                ctx,
                source_instance_id=plan.source_instance_id,
                replacement_name=plan.replacement_name,
            )
            if args.stop_source:
                _run_aws(
                    ctx,
                    [
                        "ec2",
                        "stop-instances",
                        "--instance-ids",
                        plan.source_instance_id,
                    ],
                )

        print(
            json.dumps(
                {
                    "source_instance_id": plan.source_instance_id,
                    "replacement_instance_id": replacement_instance_id,
                    "cutover_eip": bool(args.cutover_eip),
                    "stop_source": bool(args.stop_source),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
