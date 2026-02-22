#!/usr/bin/env python3
"""
Auraxis - IAM least-privilege audit helper (I8).

What it checks
- For each EC2 instance (DEV/PROD):
  - instance profile attached (if any)
  - role name behind the instance profile
  - attached managed policies
  - inline policies

What it flags (high level)
- Missing instance profile (SSM/CloudWatch/S3 automation will be brittle)
- Suspiciously broad managed policies (e.g., AdministratorAccess)

Why this exists
- I8 requires least-privilege IAM; before changing anything, we audit the
  current role and make changes intentionally.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_PROFILE = "auraxis-admin"
DEFAULT_REGION = "us-east-1"

DEFAULT_PROD_INSTANCE_ID = "i-0057e3b52162f78f8"
DEFAULT_DEV_INSTANCE_ID = "i-0bb5b392c2188dd3d"
DEFAULT_DEPLOY_DEV_ROLE = "auraxis-github-deploy-dev-ssm-role"
DEFAULT_DEPLOY_PROD_ROLE = "auraxis-github-deploy-prod-ssm-role"


@dataclass(frozen=True)
class AwsCtx:
    profile: str
    region: str


class AwsCliError(RuntimeError):
    pass


def _finding_level(finding: str) -> str:
    normalized = finding.strip().upper()
    if normalized.startswith("FAIL:"):
        return "fail"
    if normalized.startswith("WARN:"):
        return "warn"
    return "pass"


def _should_fail(summary: dict[str, int], fail_on: str) -> bool:
    if fail_on == "none":
        return False
    if fail_on == "warn":
        return summary.get("fail", 0) > 0 or summary.get("warn", 0) > 0
    return summary.get("fail", 0) > 0


def _collect_findings(report: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    for env_key in ("dev", "prod"):
        env_report = report.get(env_key)
        if isinstance(env_report, dict):
            for finding in env_report.get("findings") or []:
                if isinstance(finding, str):
                    findings.append(finding)
    deploy_roles = report.get("deploy_roles")
    if isinstance(deploy_roles, dict):
        for env_key in ("dev", "prod"):
            env_report = deploy_roles.get(env_key)
            if isinstance(env_report, dict):
                for finding in env_report.get("findings") or []:
                    if isinstance(finding, str):
                        findings.append(finding)
    return findings


def _build_summary(report: dict[str, Any]) -> dict[str, int]:
    summary = {"pass": 0, "warn": 0, "fail": 0}
    for finding in _collect_findings(report):
        level = _finding_level(finding)
        summary[level] = summary.get(level, 0) + 1
    return summary


def _run_aws(ctx: AwsCtx, args: list[str], *, expect_json: bool = True) -> Any:
    cmd = ["aws"]
    if ctx.profile:
        cmd.extend(["--profile", ctx.profile])
    cmd.extend(["--region", ctx.region, *args])
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


def _get_instance(ctx: AwsCtx, instance_id: str) -> dict[str, Any]:
    out = _run_aws(
        ctx,
        ["ec2", "describe-instances", "--instance-ids", instance_id],
    )
    reservations = out.get("Reservations") or []
    instances = (reservations[0].get("Instances") or []) if reservations else []
    if not instances:
        raise AwsCliError(f"Instance not found: {instance_id}")
    return dict(instances[0])


def _extract_name(instance: dict[str, Any]) -> str:
    for tag in instance.get("Tags") or []:
        if str(tag.get("Key")) == "Name":
            return str(tag.get("Value") or "")
    return ""


def _role_from_instance_profile_arn(profile_arn: str) -> tuple[str, list[str]]:
    # arn:aws:iam::123456789012:instance-profile/NAME
    name = profile_arn.split("/")[-1]
    return name, [name]


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _is_action_allowed(action: str, allowed_actions: set[str]) -> bool:
    action = action.lower()
    if "*" in allowed_actions:
        return True
    if action in allowed_actions:
        return True
    service, _, _ = action.partition(":")
    if f"{service}:*" in allowed_actions:
        return True
    return False


def _get_role(ctx: AwsCtx, role_name: str) -> dict[str, Any] | None:
    try:
        out = _run_aws(ctx, ["iam", "get-role", "--role-name", role_name])
    except AwsCliError:
        return None
    role = out.get("Role")
    if isinstance(role, dict):
        return role
    return None


def _iter_role_policy_documents(ctx: AwsCtx, role_name: str) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []

    inline_out = _run_aws(ctx, ["iam", "list-role-policies", "--role-name", role_name])
    for policy_name in inline_out.get("PolicyNames") or []:
        pol_out = _run_aws(
            ctx,
            [
                "iam",
                "get-role-policy",
                "--role-name",
                role_name,
                "--policy-name",
                str(policy_name),
            ],
        )
        doc = pol_out.get("PolicyDocument")
        if isinstance(doc, dict):
            docs.append(doc)

    attached_out = _run_aws(
        ctx, ["iam", "list-attached-role-policies", "--role-name", role_name]
    )
    for attached in attached_out.get("AttachedPolicies") or []:
        policy_arn = str(attached.get("PolicyArn") or "")
        if not policy_arn:
            continue
        pol_meta = _run_aws(ctx, ["iam", "get-policy", "--policy-arn", policy_arn])
        policy = pol_meta.get("Policy", {})
        version_id = str(policy.get("DefaultVersionId") or "")
        if not version_id:
            continue
        version = _run_aws(
            ctx,
            [
                "iam",
                "get-policy-version",
                "--policy-arn",
                policy_arn,
                "--version-id",
                version_id,
            ],
        )
        doc = version.get("PolicyVersion", {}).get("Document")
        if isinstance(doc, dict):
            docs.append(doc)

    return docs


def _collect_allowed_actions(policy_docs: list[dict[str, Any]]) -> set[str]:
    allowed: set[str] = set()
    for doc in policy_docs:
        statements = _ensure_list(doc.get("Statement"))
        for statement in statements:
            if not isinstance(statement, dict):
                continue
            if str(statement.get("Effect", "")).lower() != "allow":
                continue
            actions = _ensure_list(statement.get("Action"))
            for action in actions:
                if isinstance(action, str):
                    allowed.add(action.lower())
    return allowed


def _extract_oidc_subs(assume_doc: dict[str, Any]) -> list[str]:
    subs: list[str] = []
    statements = _ensure_list(assume_doc.get("Statement"))
    for statement in statements:
        if not isinstance(statement, dict):
            continue
        condition = statement.get("Condition")
        if not isinstance(condition, dict):
            continue
        for key in ("StringLike", "StringEquals"):
            branch = condition.get(key)
            if not isinstance(branch, dict):
                continue
            value = branch.get("token.actions.githubusercontent.com:sub")
            for sub in _ensure_list(value):
                if isinstance(sub, str):
                    subs.append(sub)
    return sorted(set(subs))


def audit_instance(ctx: AwsCtx, instance_id: str) -> dict[str, Any]:
    inst = _get_instance(ctx, instance_id)
    name = _extract_name(inst)
    resource = f"{instance_id} ({name})" if name else instance_id

    iam_profile = inst.get("IamInstanceProfile") or {}
    arn = str(iam_profile.get("Arn") or "")
    if not arn:
        return {
            "instance": resource,
            "instance_profile": None,
            "role": None,
            "managed_policies": [],
            "inline_policies": [],
            "findings": ["FAIL: instance has no IAM instance profile attached"],
        }

    profile_name, _ = _role_from_instance_profile_arn(arn)
    prof = _run_aws(
        ctx, ["iam", "get-instance-profile", "--instance-profile-name", profile_name]
    )
    roles = prof.get("InstanceProfile", {}).get("Roles", []) or []
    if not roles:
        return {
            "instance": resource,
            "instance_profile": profile_name,
            "role": None,
            "managed_policies": [],
            "inline_policies": [],
            "findings": ["FAIL: instance profile has no roles"],
        }

    role_name = str(roles[0].get("RoleName") or "")

    attached = _run_aws(
        ctx, ["iam", "list-attached-role-policies", "--role-name", role_name]
    )
    managed = [
        str(p.get("PolicyName"))
        for p in (attached.get("AttachedPolicies") or [])
        if p.get("PolicyName")
    ]

    inline = _run_aws(ctx, ["iam", "list-role-policies", "--role-name", role_name])
    inline_names = [str(n) for n in (inline.get("PolicyNames") or [])]

    findings: list[str] = []
    suspicious = {"AdministratorAccess", "PowerUserAccess"}
    for pol in managed:
        if pol in suspicious:
            findings.append(f"FAIL: suspicious broad managed policy attached: {pol}")
        if pol.endswith("FullAccess") and pol not in {
            "AmazonSSMFullAccess",
        }:
            findings.append(f"WARN: managed policy looks broad: {pol}")

    if not managed:
        findings.append(
            "WARN: role has no managed policies attached (verify SSM/Logs work)"
        )

    return {
        "instance": resource,
        "instance_profile": profile_name,
        "role": role_name,
        "managed_policies": sorted(managed),
        "inline_policies": sorted(inline_names),
        "findings": findings
        or ["PASS: no broad managed policies detected (basic heuristic)"],
    }


def audit_deploy_role(
    ctx: AwsCtx,
    *,
    role_name: str,
    expected_subject_hint: str,
) -> dict[str, Any]:
    role = _get_role(ctx, role_name)
    if role is None:
        return {
            "role": role_name,
            "findings": ["FAIL: role not found"],
            "allowed_actions": [],
            "trust_subjects": [],
        }

    assume_doc = role.get("AssumeRolePolicyDocument")
    trust_subjects = (
        _extract_oidc_subs(assume_doc) if isinstance(assume_doc, dict) else []
    )
    policy_docs = _iter_role_policy_documents(ctx, role_name)
    allowed_actions = _collect_allowed_actions(policy_docs)

    required_actions = {
        "ssm:sendcommand",
        "ssm:getcommandinvocation",
        "ssm:listcommandinvocations",
        "ssm:listcommands",
    }
    findings: list[str] = []
    for action in sorted(required_actions):
        if not _is_action_allowed(action, allowed_actions):
            findings.append(f"FAIL: missing required action {action}")

    if expected_subject_hint not in trust_subjects:
        findings.append(
            "WARN: expected OIDC subject hint not found in trust policy: "
            f"{expected_subject_hint}"
        )

    if _is_action_allowed("*", allowed_actions):
        findings.append("FAIL: wildcard '*' action detected in deploy role")

    return {
        "role": role_name,
        "allowed_actions": sorted(allowed_actions),
        "trust_subjects": trust_subjects,
        "findings": findings
        or ["PASS: deploy role has required SSM actions and expected trust hints"],
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Auraxis IAM audit helper (I8)")
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--prod-instance-id", default=DEFAULT_PROD_INSTANCE_ID)
    p.add_argument("--dev-instance-id", default=DEFAULT_DEV_INSTANCE_ID)
    p.add_argument("--deploy-dev-role", default=DEFAULT_DEPLOY_DEV_ROLE)
    p.add_argument("--deploy-prod-role", default=DEFAULT_DEPLOY_PROD_ROLE)
    p.add_argument(
        "--fail-on",
        choices=("none", "warn", "fail"),
        default="fail",
        help=(
            "Failure threshold for findings. "
            "fail=only FAIL, warn=FAIL/WARN, none=always 0."
        ),
    )
    p.add_argument(
        "--output-json",
        default="",
        help="Optional path to persist JSON report (e.g. reports/aws-iam-audit.json).",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    ctx = AwsCtx(profile=args.profile, region=args.region)
    dev_subject_hint = "repo:italofelipe/auraxis-api:environment:dev"
    prod_subject_hint = "repo:italofelipe/auraxis-api:environment:prod"
    report = {
        "dev": audit_instance(ctx, str(args.dev_instance_id)),
        "prod": audit_instance(ctx, str(args.prod_instance_id)),
        "deploy_roles": {
            "dev": audit_deploy_role(
                ctx,
                role_name=str(args.deploy_dev_role),
                expected_subject_hint=dev_subject_hint,
            ),
            "prod": audit_deploy_role(
                ctx,
                role_name=str(args.deploy_prod_role),
                expected_subject_hint=prod_subject_hint,
            ),
        },
    }
    summary = _build_summary(report)
    report["summary"] = summary
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if _should_fail(summary, str(args.fail_on)):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
