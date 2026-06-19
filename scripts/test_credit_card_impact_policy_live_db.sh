#!/usr/bin/env bash
# Verifies credit-card impact policy behavior against a real PostgreSQL DB.
#
# The script starts an ephemeral postgres:16 container, applies all Alembic
# migrations, runs the opt-in live DB pytest, and removes the container.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="auraxis-pg-credit-card-policy-test"
PG_PORT="${CREDIT_CARD_POLICY_TEST_PG_PORT:-5434}"
PG_PASSWORD="credit_card_policy_test_secret"
PG_DB="credit_card_policy_testdb"
PG_USER="postgres"
DATABASE_URL="postgresql://${PG_USER}:${PG_PASSWORD}@localhost:${PG_PORT}/${PG_DB}"
FLASK_CMD="${FLASK_CMD:-scripts/python_tool.sh flask}"
PYTEST_CMD="${PYTEST_CMD:-scripts/python_tool.sh pytest}"

cleanup() {
  echo "[credit-card-policy-live-db] Removing container ${CONTAINER}..."
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "${ROOT_DIR}"

echo "[credit-card-policy-live-db] Starting postgres:16 on port ${PG_PORT}..."
docker run -d \
  --name "${CONTAINER}" \
  -e POSTGRES_PASSWORD="${PG_PASSWORD}" \
  -e POSTGRES_DB="${PG_DB}" \
  -e POSTGRES_USER="${PG_USER}" \
  -p "${PG_PORT}:5432" \
  --tmpfs /var/lib/postgresql/data \
  public.ecr.aws/docker/library/postgres:16 >/dev/null

echo "[credit-card-policy-live-db] Waiting for PostgreSQL..."
for i in $(seq 1 30); do
  if docker exec "${CONTAINER}" pg_isready -U "${PG_USER}" -q 2>/dev/null; then
    echo "[credit-card-policy-live-db] PostgreSQL ready."
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo "[credit-card-policy-live-db] ERROR: PostgreSQL was not ready in 30s." >&2
    exit 1
  fi
done

echo "[credit-card-policy-live-db] Applying migrations..."
DATABASE_URL="${DATABASE_URL}" ${FLASK_CMD} --app run db upgrade

echo "[credit-card-policy-live-db] Running live DB pytest..."
AURAXIS_LIVE_DATABASE_URL="${DATABASE_URL}" \
  ${PYTEST_CMD} tests/test_credit_card_impact_policy_live_db.py -q

echo "[credit-card-policy-live-db] Live DB policy flow passed."
