#!/usr/bin/env bash
# check-openapi-drift.sh — POSTMAN-06: detect uncommitted OpenAPI spec changes.
#
# Generates a fresh openapi.json from the live app and compares it against the
# committed version. Exits non-zero if they differ, which means someone changed
# a controller or schema without regenerating the spec.
#
# Usage:
#   bash scripts/check-openapi-drift.sh
#
# To fix a drift failure:
#   flask openapi-export --output openapi.json && git add openapi.json

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMMITTED_SPEC="openapi.json"
TEMP_SPEC="$(mktemp /tmp/openapi-drift-XXXXXX.json)"
TEMP_DB="$(mktemp /tmp/openapi-drift-XXXXXX.sqlite3)"

cleanup() {
  rm -f "$TEMP_SPEC" "$TEMP_DB"
}
trap cleanup EXIT

if [[ ! -f "$COMMITTED_SPEC" ]]; then
  echo "[openapi-drift] ERROR: $COMMITTED_SPEC not found."
  echo "[openapi-drift] Run: flask openapi-export --output openapi.json"
  exit 1
fi

# Resolve Python — prefer venv, fallback to system. The venv is also probed by
# actually running it: when the repo is mounted into a Linux container (the
# default mode of run_ci_quality_local.sh) the committed macOS .venv binary
# exists but cannot execute.
PYTHON_BIN="${CONTRACTS_PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python3}"
if [[ ! -x "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" -c "" > /dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

echo "[openapi-drift] Generating fresh spec from live app..."
FLASK_TESTING=true \
SECURITY_ENFORCE_STRONG_SECRETS=false \
DOCS_EXPOSURE_POLICY=public \
DATABASE_URL="sqlite:///${TEMP_DB}" \
SECRET_KEY="drift-check-key-with-64-chars-minimum-for-jwt-signing-000001" \
JWT_SECRET_KEY="drift-check-jwt-key-with-64-chars-minimum-for-signing-002" \
"$PYTHON_BIN" - "$TEMP_SPEC" <<'PY'
import json
import sys

from app import create_app
from app.cli.openapi_export import _stabilize_parameters
from app.extensions.database import db

output_path = sys.argv[1]
app = create_app()
app.config["TESTING"] = True

with app.app_context():
    db.drop_all()
    db.create_all()

with app.test_client() as client:
    response = client.get("/docs/swagger/")
    if response.status_code != 200:
        raise RuntimeError(f"Swagger endpoint returned {response.status_code}")
    spec = response.get_json() or {}

spec = _stabilize_parameters(spec)

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(spec, f, ensure_ascii=False, indent=2, sort_keys=True)
    f.write("\n")
PY

if diff -q "$COMMITTED_SPEC" "$TEMP_SPEC" > /dev/null 2>&1; then
  echo "[openapi-drift] OK — openapi.json is up to date."
  exit 0
else
  echo "[openapi-drift] DRIFT DETECTED — openapi.json is stale."
  echo ""
  echo "Diff (committed vs live):"
  diff --unified=3 "$COMMITTED_SPEC" "$TEMP_SPEC" | head -50
  echo ""
  echo "To fix:"
  echo "  flask openapi-export --output openapi.json && git add openapi.json"
  exit 1
fi
