#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
CI_LOCAL_PYTHON_IMAGE="${CI_LOCAL_PYTHON_IMAGE:-public.ecr.aws/docker/library/python:3.13-slim}"
# shellcheck source=./lib_python.sh
source "${ROOT_DIR}/scripts/lib_python.sh"

MODE="docker"
if [[ "${1:-}" == "--local" ]]; then
  MODE="local"
fi

if [[ "$MODE" == "docker" ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required for default mode. Use '--local' to run with current environment." >&2
    exit 1
  fi

  echo "[quality-local] Running CI quality pipeline in ${CI_LOCAL_PYTHON_IMAGE} container..."
  docker run --rm \
    -v "$ROOT_DIR:/workspace" \
    -w /workspace \
    "$CI_LOCAL_PYTHON_IMAGE" \
    bash -lc "python3 scripts/check_feature_flags.py && \
      python3 scripts/repo_hygiene_check.py && \
      python3 scripts/graphql_auth_config_check.py && \
      python3 scripts/alembic_single_head_check.py && \
      python -m pip install --upgrade pip && \
      python -m pip install -r requirements.txt -r requirements-dev.txt && \
      python3 scripts/security_exception_governance.py check && \
      python -m pip_audit -r requirements.txt \$(python3 scripts/security_exception_governance.py pip-audit-args) && \
      python -m ruff format --check . && \
      python -m ruff check app tests config run.py run_without_db.py && \
      python -m mypy --no-incremental app && \
      python -m bandit -r app -lll -iii && \
      pytest -m 'not schemathesis' --cov=app --cov-fail-under=85 --cov-report=term-missing"
  echo "[quality-local] All quality checks passed (Docker / Python 3.13)."
  exit 0
fi

PYTHON_BIN="$(resolve_repo_python "$ROOT_DIR")"

echo "[quality-local] Running CI quality pipeline in local environment with ${PYTHON_BIN}..."
python3 scripts/check_feature_flags.py
python3 scripts/repo_hygiene_check.py
python3 scripts/graphql_auth_config_check.py
python3 scripts/alembic_single_head_check.py
python3 scripts/security_exception_governance.py check
"${PYTHON_BIN}" -m pip_audit -r requirements.txt $(python3 scripts/security_exception_governance.py pip-audit-args)
"${PYTHON_BIN}" -m ruff format --check .
"${PYTHON_BIN}" -m ruff check app tests config run.py run_without_db.py
"${PYTHON_BIN}" -m mypy --no-incremental app
"${PYTHON_BIN}" -m bandit -r app -lll -iii
"${PYTHON_BIN}" -m pytest -m "not schemathesis" --cov=app --cov-fail-under=85 --cov-report=term-missing
echo "[quality-local] All quality checks passed (local environment)."
