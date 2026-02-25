#!/usr/bin/env python3
"""Validate feature flag metadata hygiene for PLT4.1."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ALLOWED_TYPES = {"release", "experiment", "kill-switch"}
ALLOWED_STATUS = {
    "draft",
    "enabled-dev",
    "enabled-staging",
    "enabled-prod",
    "cleanup-pending",
    "removed",
}


@dataclass
class ValidationError:
    message: str


def parse_iso_date(
    raw: Any, key: str, field_name: str, errors: list[ValidationError]
) -> date | None:
    if not isinstance(raw, str):
        errors.append(
            ValidationError(f"{key}: field '{field_name}' must use YYYY-MM-DD")
        )
        return None

    try:
        parsed = date.fromisoformat(raw)
    except ValueError:
        errors.append(
            ValidationError(f"{key}: field '{field_name}' is not a valid calendar date")
        )
        return None

    return parsed


def get_flag_key(flag: dict[str, Any], errors: list[ValidationError]) -> str | None:
    key = str(flag.get("key", "")).strip()
    if not key:
        errors.append(ValidationError("invalid flag entry: missing non-empty 'key'"))
        return None
    return key


def validate_key(
    key: str, prefix: str, seen_keys: set[str], errors: list[ValidationError]
) -> None:
    if not key.startswith(f"{prefix}."):
        errors.append(ValidationError(f"{key}: key must start with '{prefix}.'"))

    if key in seen_keys:
        errors.append(ValidationError(f"{key}: duplicate key detected"))
        return

    seen_keys.add(key)


def validate_owner_type_status(
    key: str, flag: dict[str, Any], errors: list[ValidationError]
) -> str:
    owner = str(flag.get("owner", "")).strip()
    raw_type = str(flag.get("type", "")).strip()
    status = str(flag.get("status", "")).strip()

    if not owner:
        errors.append(ValidationError(f"{key}: missing required field 'owner'"))

    if raw_type not in ALLOWED_TYPES:
        errors.append(ValidationError(f"{key}: invalid 'type' ({raw_type or 'empty'})"))

    if status not in ALLOWED_STATUS:
        errors.append(ValidationError(f"{key}: invalid 'status' ({status or 'empty'})"))

    return status


def validate_dates(
    key: str,
    flag: dict[str, Any],
    status: str,
    today: date,
    errors: list[ValidationError],
) -> None:
    created_at = parse_iso_date(flag.get("createdAt"), key, "createdAt", errors)
    remove_by = parse_iso_date(flag.get("removeBy"), key, "removeBy", errors)

    if created_at and remove_by and remove_by < created_at:
        errors.append(
            ValidationError(f"{key}: 'removeBy' cannot be before 'createdAt'")
        )

    if remove_by and status != "removed" and remove_by < today:
        details = f"{key}: flag is expired ({remove_by.isoformat()})"
        details += f" and not removed (status={status or 'empty'})"
        errors.append(ValidationError(details))


def validate_flag(
    flag: Any,
    prefix: str,
    today: date,
    seen_keys: set[str],
    errors: list[ValidationError],
) -> None:
    if not isinstance(flag, dict):
        errors.append(
            ValidationError("invalid flag entry: every item must be an object")
        )
        return

    key = get_flag_key(flag, errors)
    if not key:
        return

    validate_key(key, prefix, seen_keys, errors)
    status = validate_owner_type_status(key, flag, errors)
    validate_dates(key, flag, status, today, errors)


def validate_flags(flags: list[dict[str, Any]], prefix: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    seen_keys: set[str] = set()
    today = date.today()

    for flag in flags:
        validate_flag(flag, prefix, today, seen_keys, errors)

    return errors


def load_flags(catalog_path: Path) -> list[dict[str, Any]]:
    raw = catalog_path.read_text(encoding="utf-8")
    parsed = json.loads(raw)

    flags = parsed.get("flags")
    if not isinstance(flags, list):
        raise ValueError("catalog must contain a top-level 'flags' array")

    return flags


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    catalog_path = root_dir / "config" / "feature-flags.json"

    try:
        flags = load_flags(catalog_path)
        errors = validate_flags(flags, prefix="api")
    except Exception as exc:  # pragma: no cover - defensive failure path
        print("[feature-flags-hygiene] FAILED", file=sys.stderr)
        print(f" - {exc}", file=sys.stderr)
        return 1

    if errors:
        print("[feature-flags-hygiene] FAILED", file=sys.stderr)
        for error in errors:
            print(f" - {error.message}", file=sys.stderr)
        return 1

    print(f"[feature-flags-hygiene] OK ({len(flags)} flags)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
