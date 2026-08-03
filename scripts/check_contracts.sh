#!/usr/bin/env bash
# check_contracts.sh — lock the committed API contract snapshots (#1536).
#
# Regenerates both public contracts from the Python source and fails when the
# versioned snapshot is stale:
#
#   openapi.json                     ← REST (flask-apispec)
#   schema.graphql                   ← GraphQL SDL
#   graphql.introspection.json       ← GraphQL introspection
#   graphql.operations.manifest.json ← GraphQL operation catalogue
#
# Why a dedicated gate: `openapi-diff.yml` only runs when `openapi.json` itself
# changes, and `postman-sync.yml` only runs on push to master. Neither catches
# the dangerous case — a controller/schema change merged with a **stale**
# snapshot, which silently breaks the web codegen. This script runs on every PR.
#
# Usage:
#   bash scripts/check_contracts.sh          # both contracts
#   bash scripts/check_contracts.sh --openapi
#   bash scripts/check_contracts.sh --graphql
#
# To fix a failure, regenerate and commit:
#   flask openapi-export --output openapi.json
#   python3 scripts/export_graphql_docs.py --source runtime

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CHECK_OPENAPI=1
CHECK_GRAPHQL=1
case "${1:-}" in
  --openapi) CHECK_GRAPHQL=0 ;;
  --graphql) CHECK_OPENAPI=0 ;;
  "") ;;
  *)
    echo "[contracts] Unknown argument: $1 (use --openapi or --graphql)" >&2
    exit 2
    ;;
esac

# Resolve Python — prefer the repo venv, fallback to system. The venv is probed
# by running it: inside a Linux container the mounted macOS .venv binary exists
# but cannot execute.
PYTHON_BIN="${CONTRACTS_PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python3}"
if [[ ! -x "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -c "" > /dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

FAILED=0

if [[ "$CHECK_OPENAPI" == "1" ]]; then
  echo "[contracts] Checking OpenAPI snapshot (openapi.json)..."
  if bash "${ROOT_DIR}/scripts/check-openapi-drift.sh"; then
    echo "[contracts] OpenAPI snapshot OK."
  else
    FAILED=1
    echo "::error file=openapi.json::openapi.json está defasado em relação ao código." \
      "Rode 'flask openapi-export --output openapi.json' e commite o resultado."
  fi
fi

if [[ "$CHECK_GRAPHQL" == "1" ]]; then
  echo "[contracts] Checking GraphQL snapshots (schema.graphql + artefatos)..."
  if "$PYTHON_BIN" "${ROOT_DIR}/scripts/export_graphql_docs.py" --source runtime --check; then
    echo "[contracts] GraphQL snapshots OK."
  else
    FAILED=1
    echo "::error file=schema.graphql::Artefatos GraphQL defasados." \
      "Rode 'python3 scripts/export_graphql_docs.py --source runtime' e commite o resultado."
  fi
fi

if [[ "$FAILED" -ne 0 ]]; then
  echo "[contracts] DRIFT DETECTED — snapshot de contrato desatualizado."
  exit 1
fi

echo "[contracts] OK — snapshots de contrato em dia."
