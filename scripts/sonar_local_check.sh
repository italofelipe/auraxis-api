#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SONAR_HOST_URL="${SONAR_HOST_URL:-https://sonarcloud.io}"
SONAR_LOCAL_MODE="${SONAR_LOCAL_MODE:-advisory}"

if [[ "${CI:-false}" == "true" ]]; then
  SONAR_LOCAL_MODE="enforce"
fi

if [[ "${AURAXIS_ENFORCE_LOCAL_SONAR:-false}" == "true" ]]; then
  SONAR_LOCAL_MODE="enforce"
fi

normalize_env_var() {
  local value="$1"
  # Remove CR/LF and trim leading/trailing whitespace.
  printf '%s' "$value" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

required_vars=(
  "SONAR_TOKEN"
  "SONAR_PROJECT_KEY"
  "SONAR_ORGANIZATION"
)

handle_soft_failure() {
  local message="$1"
  if [[ "$SONAR_LOCAL_MODE" == "enforce" ]]; then
    echo "$message" >&2
    exit 1
  fi
  echo "[sonar-local] advisory: $message"
  echo "[sonar-local] advisory: continuing local push; CI Sonar gate remains mandatory."
  exit 0
}

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    handle_soft_failure "Missing required environment variable: ${var_name}"
  fi
done

SONAR_TOKEN="$(normalize_env_var "${SONAR_TOKEN}")"
SONAR_PROJECT_KEY="$(normalize_env_var "${SONAR_PROJECT_KEY}")"
SONAR_ORGANIZATION="$(normalize_env_var "${SONAR_ORGANIZATION}")"

for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    handle_soft_failure "Environment variable is empty after normalization: ${var_name}"
  fi
done

if ! command -v sonar-scanner >/dev/null 2>&1; then
  handle_soft_failure "sonar-scanner not found in PATH. Install sonar-scanner to run local Sonar checks."
fi

if ! command -v curl >/dev/null 2>&1; then
  handle_soft_failure "curl not found in PATH."
fi

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

echo "[sonar-local] Running tests with coverage..."
"$PYTHON_BIN" -m pytest -p no:schemathesis -m "not schemathesis" -q --disable-warnings --cov=app --cov-report=xml:coverage.xml

SONAR_LOCAL_MAX_ATTEMPTS="${SONAR_LOCAL_MAX_ATTEMPTS:-6}"
SONAR_LOCAL_RETRY_BACKOFF_SECONDS="${SONAR_LOCAL_RETRY_BACKOFF_SECONDS:-20}"
SONAR_LOCK_MESSAGE="Another SonarQube analysis is already in progress for this project"

run_sonar_scanner() {
  sonar-scanner \
    -Dsonar.host.url="${SONAR_HOST_URL}" \
    -Dsonar.token="${SONAR_TOKEN}" \
    -Dsonar.organization="${SONAR_ORGANIZATION}" \
    -Dsonar.projectKey="${SONAR_PROJECT_KEY}" \
    -Dsonar.python.coverage.reportPaths=coverage.xml \
    -Dsonar.qualitygate.wait=true \
    -Dsonar.qualitygate.timeout=300
}

echo "[sonar-local] Running sonar-scanner with quality gate wait..."
attempt=1
while [[ "$attempt" -le "$SONAR_LOCAL_MAX_ATTEMPTS" ]]; do
  scanner_log="$(mktemp)"
  echo "[sonar-local] sonar-scanner attempt ${attempt}/${SONAR_LOCAL_MAX_ATTEMPTS}"
  set +e
  run_sonar_scanner 2>&1 | tee "$scanner_log"
  scanner_exit_code="${PIPESTATUS[0]}"
  set -e

  if [[ "$scanner_exit_code" -eq 0 ]]; then
    rm -f "$scanner_log"
    break
  fi

  if grep -q "$SONAR_LOCK_MESSAGE" "$scanner_log" && [[ "$attempt" -lt "$SONAR_LOCAL_MAX_ATTEMPTS" ]]; then
    sleep_seconds=$((SONAR_LOCAL_RETRY_BACKOFF_SECONDS * attempt))
    echo "[sonar-local] Analysis lock detected. Retrying in ${sleep_seconds}s..."
    rm -f "$scanner_log"
    sleep "$sleep_seconds"
    attempt=$((attempt + 1))
    continue
  fi

  rm -f "$scanner_log"
  if [[ "$SONAR_LOCAL_MODE" == "enforce" ]]; then
    exit "$scanner_exit_code"
  fi
  handle_soft_failure "sonar-scanner failed locally (non-blocking advisory mode)."
done

echo "[sonar-local] Validating ratings are A..."
measures_json="$(curl -sf -u "${SONAR_TOKEN}:" \
  "${SONAR_HOST_URL}/api/measures/component?component=${SONAR_PROJECT_KEY}&metricKeys=security_rating,reliability_rating,sqale_rating")"

set +e
MEASURES_JSON="$measures_json" "$PYTHON_BIN" - <<'PY'
import json
import os
import sys


def is_a(value: str) -> bool:
    normalized = value.strip().upper()
    if normalized == "A":
        return True
    try:
        return float(normalized) <= 1.0
    except ValueError:
        return False


payload = json.loads(os.environ["MEASURES_JSON"])
measures = payload.get("component", {}).get("measures", [])
metrics = {item["metric"]: item.get("value", "") for item in measures}

required = {
    "security_rating": "Security",
    "reliability_rating": "Reliability",
    "sqale_rating": "Maintainability",
}

missing = [metric for metric in required if metric not in metrics]
if missing:
    print(f"Missing Sonar metrics in response: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)

non_a = []
for metric, label in required.items():
    if not is_a(metrics[metric]):
        non_a.append(f"{label}={metrics[metric]}")

if non_a:
    print("Sonar ratings below A: " + ", ".join(non_a), file=sys.stderr)
    sys.exit(1)

print("Sonar ratings check passed: Security=A, Reliability=A, Maintainability=A")
PY
rating_check_exit_code="$?"
set -e

if [[ "$rating_check_exit_code" -ne 0 ]]; then
  if [[ "$SONAR_LOCAL_MODE" == "enforce" ]]; then
    exit "$rating_check_exit_code"
  fi
  handle_soft_failure "Sonar rating check not A in local advisory mode."
fi

echo "[sonar-local] Done."
