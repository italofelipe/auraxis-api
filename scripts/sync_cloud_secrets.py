#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast

ENV_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SecretSyncError(RuntimeError):
    pass


def _run_aws_command(arguments: list[str]) -> dict[str, Any]:
    process = subprocess.run(
        ["aws", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise SecretSyncError(
            "AWS CLI command failed: "
            + " ".join(arguments)
            + f"\n{process.stderr.strip()}"
        )

    try:
        parsed = json.loads(process.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SecretSyncError("Failed to parse AWS CLI JSON output.") from exc
    if not isinstance(parsed, dict):
        raise SecretSyncError("Unexpected AWS CLI payload format.")
    return cast(dict[str, Any], parsed)


def _normalize_env_key(name: str, prefix: str | None = None) -> str:
    candidate = name.strip()
    if prefix:
        normalized_prefix = prefix.rstrip("/")
        if candidate.startswith(normalized_prefix):
            candidate = candidate[len(normalized_prefix) :].lstrip("/")
    if "/" in candidate:
        candidate = candidate.split("/")[-1]
    candidate = candidate.strip().upper().replace("-", "_")
    return candidate


def _validate_env_key(key: str) -> None:
    if not ENV_KEY_PATTERN.match(key):
        raise SecretSyncError(
            f"Invalid env key generated from secret name: '{key}'. "
            "Use names compatible with [A-Z][A-Z0-9_]*."
        )


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SecretSyncError(f"Base env file not found: {path}")

    resolved: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        raw_key, raw_value = line.split("=", 1)
        key = _normalize_env_key(raw_key)
        _validate_env_key(key)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        resolved[key] = value
    return resolved


def merge_env_values(
    *,
    base_values: dict[str, str] | None = None,
    cloud_values: dict[str, str] | None = None,
    override_values: dict[str, str] | None = None,
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for candidate in (base_values or {}, cloud_values or {}, override_values or {}):
        for key, value in candidate.items():
            normalized_key = _normalize_env_key(key)
            _validate_env_key(normalized_key)
            merged[normalized_key] = str(value)
    return merged


def load_ssm_parameters(path: str, region: str) -> dict[str, str]:
    if not path.strip():
        raise SecretSyncError("SSM path is required.")

    payload = _run_aws_command(
        [
            "ssm",
            "get-parameters-by-path",
            "--path",
            path,
            "--recursive",
            "--with-decryption",
            "--region",
            region,
            "--output",
            "json",
        ]
    )
    parameters = payload.get("Parameters", [])
    if not isinstance(parameters, list):
        raise SecretSyncError("Unexpected SSM response format.")

    resolved: dict[str, str] = {}
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        raw_name = str(parameter.get("Name", ""))
        raw_value = str(parameter.get("Value", ""))
        key = _normalize_env_key(raw_name, prefix=path)
        _validate_env_key(key)
        resolved[key] = raw_value

    if not resolved:
        raise SecretSyncError(
            f"No parameters found under path '{path}'. Check AWS region/path."
        )
    return resolved


def load_secrets_manager(secret_id: str, region: str) -> dict[str, str]:
    if not secret_id.strip():
        raise SecretSyncError("Secrets Manager secret id is required.")

    payload = _run_aws_command(
        [
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            secret_id,
            "--region",
            region,
            "--output",
            "json",
        ]
    )
    secret_string = payload.get("SecretString")
    if not isinstance(secret_string, str) or not secret_string.strip():
        raise SecretSyncError(
            "SecretString not found or empty. Binary secrets are not supported."
        )

    try:
        raw_secret = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise SecretSyncError(
            "SecretString must be a JSON object with env-style keys."
        ) from exc

    if not isinstance(raw_secret, dict):
        raise SecretSyncError("SecretString JSON must be an object.")

    resolved: dict[str, str] = {}
    for raw_key, raw_value in raw_secret.items():
        key = _normalize_env_key(str(raw_key))
        _validate_env_key(key)
        resolved[key] = str(raw_value)

    if not resolved:
        raise SecretSyncError("Secrets Manager payload is empty.")
    return resolved


def _format_env_value(value: str) -> str:
    safe_chars = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._:/@"
    )
    if value and all(char in safe_chars for char in value):
        return value
    escaped = value.replace("'", "'\"'\"'")
    return f"'{escaped}'"


def write_env_file(output_path: Path, values: dict[str, str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# generated by scripts/sync_cloud_secrets.py",
        "# do not commit this file",
    ]
    for key in sorted(values.keys()):
        lines.append(f"{key}={_format_env_value(values[key])}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output_path.chmod(0o600)


def _parse_required_keys(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip().upper() for item in raw.split(",") if item.strip()}


def _parse_override_env(raw_items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for item in raw_items:
        if "=" not in item:
            raise SecretSyncError(
                f"Override values must use KEY=VALUE format. Received: '{item}'"
            )
        raw_key, raw_value = item.split("=", 1)
        key = _normalize_env_key(raw_key)
        _validate_env_key(key)
        overrides[key] = raw_value
    return overrides


def _validate_required_keys(values: dict[str, str], required_keys: set[str]) -> None:
    missing = sorted(key for key in required_keys if key not in values)
    if missing:
        raise SecretSyncError(
            "Missing required keys in cloud secrets: " + ", ".join(missing)
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync app secrets from AWS SSM/Secrets Manager into a local env file "
            "for Docker Compose runtime."
        )
    )
    parser.add_argument(
        "--backend",
        choices=["ssm", "secretsmanager"],
        default=os.getenv("AURAXIS_SECRETS_BACKEND", "ssm"),
        help="Cloud secrets backend.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", "us-east-1"),
        help="AWS region.",
    )
    parser.add_argument(
        "--output",
        default=".env.runtime",
        help="Output env file path.",
    )
    parser.add_argument(
        "--ssm-path",
        default=os.getenv("AURAXIS_SSM_PATH", ""),
        help="SSM prefix path, e.g. /auraxis/prod",
    )
    parser.add_argument(
        "--secret-id",
        default=os.getenv("AURAXIS_SECRETS_MANAGER_ID", ""),
        help="Secrets Manager secret id.",
    )
    parser.add_argument(
        "--required-keys",
        default=os.getenv(
            "AURAXIS_REQUIRED_SECRET_KEYS",
            "SECRET_KEY,JWT_SECRET_KEY,DB_HOST,DB_PORT,DB_NAME,DB_USER,DB_PASS",
        ),
        help="Comma-separated required env keys.",
    )
    parser.add_argument(
        "--base-env",
        default="",
        help="Optional base env template to merge before cloud secrets.",
    )
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        help="Explicit override in KEY=VALUE format. May be repeated.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    required_keys = _parse_required_keys(args.required_keys)
    base_values = (
        parse_env_file(Path(args.base_env).resolve()) if args.base_env.strip() else {}
    )
    override_values = _parse_override_env(list(args.overrides))

    if args.backend == "ssm":
        cloud_values = load_ssm_parameters(args.ssm_path, args.region)
    else:
        cloud_values = load_secrets_manager(args.secret_id, args.region)

    values = merge_env_values(
        base_values=base_values,
        cloud_values=cloud_values,
        override_values=override_values,
    )
    _validate_required_keys(values, required_keys)
    output_path = Path(args.output).resolve()
    write_env_file(output_path, values)
    print(f"Secrets synced to: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SecretSyncError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from exc
