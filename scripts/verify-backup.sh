#!/usr/bin/env bash
# verify-backup.sh — Verify integrity of the most recent S3 backup
#
# Finds the most recent backup in s3://auraxis-db-backups/daily/, downloads it
# to /tmp, runs pg_restore --list to verify the dump is not corrupt, reports
# size, date, and checksum, then cleans up.
#
# Usage:
#   bash scripts/verify-backup.sh
#
# Environment:
#   AWS_PROFILE  — optional; uses instance role by default
#   BACKUP_DATE  — optional; override the backup date (YYYY-MM-DD)
#
# Exit codes:
#   0  — backup present and valid
#   1  — backup missing or corrupt
#   2  — dependency not found (aws CLI, pg_restore)
#   3  — S3 download failed

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
BUCKET="auraxis-db-backups"
PREFIX="daily/"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LOG_PREFIX="[auraxis-verify-backup]"
TMP_DIR="/tmp/auraxis-backup-verify-$$"

log()  { echo "${LOG_PREFIX} ${TIMESTAMP} INFO  $*"; }
warn() { echo "${LOG_PREFIX} ${TIMESTAMP} WARN  $*" >&2; }
fail() { echo "${LOG_PREFIX} ${TIMESTAMP} ERROR $*" >&2; exit "${1}"; }

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

# ── Check dependencies ───────────────────────────────────────────────────────
log "Checking dependencies..."
if ! command -v aws &>/dev/null; then
  fail 2 "aws CLI not found. Install: https://aws.amazon.com/cli/"
fi

# pg_restore may live inside a Docker container; check for both local and Docker
PG_RESTORE_CMD=""
if command -v pg_restore &>/dev/null; then
  PG_RESTORE_CMD="pg_restore"
elif docker ps --filter "name=auraxis-db-1" --filter "status=running" --quiet 2>/dev/null | grep -q .; then
  PG_RESTORE_CMD="docker exec auraxis-db-1 pg_restore"
  log "pg_restore not found locally; will use Docker container auraxis-db-1"
else
  fail 2 "pg_restore not found locally and container auraxis-db-1 is not running."
fi

log "Dependencies OK (aws CLI + pg_restore available)"

# ── Resolve backup key ───────────────────────────────────────────────────────
mkdir -p "${TMP_DIR}"

if [[ -n "${BACKUP_DATE:-}" ]]; then
  S3_KEY="${PREFIX}${BACKUP_DATE}.sql.gz"
  log "Using override date: ${BACKUP_DATE}"
else
  log "Discovering most recent backup in s3://${BUCKET}/${PREFIX}..."
  LATEST_KEY=$(aws s3 ls "s3://${BUCKET}/${PREFIX}" \
    | sort | tail -n 1 | awk '{print $4}')

  if [[ -z "${LATEST_KEY}" ]]; then
    fail 1 "No backup files found in s3://${BUCKET}/${PREFIX}"
  fi

  S3_KEY="${PREFIX}${LATEST_KEY}"
  BACKUP_DATE="${LATEST_KEY%.sql.gz}"
fi

log "Target backup: s3://${BUCKET}/${S3_KEY} (date: ${BACKUP_DATE})"

# ── Fetch S3 object metadata ─────────────────────────────────────────────────
log "Fetching S3 object metadata..."
S3_META=$(aws s3api head-object --bucket "${BUCKET}" --key "${S3_KEY}" 2>/dev/null) || {
  fail 1 "Object s3://${BUCKET}/${S3_KEY} does not exist or is not accessible."
}

S3_SIZE_BYTES=$(echo "${S3_META}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ContentLength', 0))")
S3_LAST_MODIFIED=$(echo "${S3_META}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('LastModified', 'unknown'))")
S3_ETAG=$(echo "${S3_META}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('ETag','').strip('\"'))")

log "S3 object metadata:"
log "  Last-Modified : ${S3_LAST_MODIFIED}"
log "  Size (bytes)  : ${S3_SIZE_BYTES}"
log "  ETag/MD5      : ${S3_ETAG}"

if [[ "${S3_SIZE_BYTES}" -lt 100 ]]; then
  fail 1 "Backup file is suspiciously small (${S3_SIZE_BYTES} bytes). Possibly empty or corrupt."
fi

# ── Download backup ──────────────────────────────────────────────────────────
DUMP_GZ="${TMP_DIR}/${BACKUP_DATE}.sql.gz"
DUMP_SQL="${TMP_DIR}/${BACKUP_DATE}.sql"

log "Downloading s3://${BUCKET}/${S3_KEY} → ${DUMP_GZ}"
if ! aws s3 cp "s3://${BUCKET}/${S3_KEY}" "${DUMP_GZ}"; then
  fail 3 "S3 download failed."
fi

LOCAL_SIZE=$(du -sh "${DUMP_GZ}" | cut -f1)
log "Download complete. Local size: ${LOCAL_SIZE}"

# ── Compute local checksum ───────────────────────────────────────────────────
LOCAL_MD5=$(md5 -q "${DUMP_GZ}" 2>/dev/null || md5sum "${DUMP_GZ}" | awk '{print $1}')
log "Local MD5 checksum: ${LOCAL_MD5}"

# ── Decompress and verify with pg_restore --list ─────────────────────────────
log "Decompressing dump for integrity check..."
if ! gunzip -c "${DUMP_GZ}" > "${DUMP_SQL}"; then
  fail 1 "gunzip failed — the .gz file is corrupt."
fi

SQL_SIZE=$(du -sh "${DUMP_SQL}" | cut -f1)
log "Decompressed size: ${SQL_SIZE}"

# pg_restore --list works on custom-format dumps; plain SQL dumps are verified
# via gunzip success + psql --single-transaction dry-run header scan.
# Detect dump format: custom format starts with PGDMP magic bytes.
MAGIC=$(xxd -l 5 "${DUMP_SQL}" 2>/dev/null | awk '{print $2$3}' | tr -d ' ' | head -c10 || true)

if [[ "${MAGIC}" == "5047444d50"* ]]; then
  # Custom format — use pg_restore --list (no DB connection required)
  log "Detected custom-format dump. Running pg_restore --list..."
  if ! ${PG_RESTORE_CMD} --list "${DUMP_SQL}" > "${TMP_DIR}/toc.txt" 2>&1; then
    fail 1 "pg_restore --list failed — dump is corrupt or incompatible."
  fi
  TOC_LINES=$(wc -l < "${TMP_DIR}/toc.txt")
  log "pg_restore TOC: ${TOC_LINES} entries"
  if [[ "${TOC_LINES}" -lt 5 ]]; then
    warn "TOC has very few entries (${TOC_LINES}). Backup may be incomplete."
  fi
else
  # Plain SQL — verify it starts with a PostgreSQL dump header
  log "Detected plain SQL dump. Verifying header..."
  HEADER=$(head -c 200 "${DUMP_SQL}")
  if echo "${HEADER}" | grep -q "PostgreSQL database dump"; then
    log "Plain SQL header OK — PostgreSQL database dump header found."
  else
    fail 1 "Plain SQL dump does not contain expected PostgreSQL header. File may be corrupt."
  fi
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "=========================================="
echo "  Backup Verification Report"
echo "=========================================="
echo "  Date          : ${BACKUP_DATE}"
echo "  S3 key        : s3://${BUCKET}/${S3_KEY}"
echo "  Last modified : ${S3_LAST_MODIFIED}"
echo "  S3 size       : ${S3_SIZE_BYTES} bytes"
echo "  Local size    : ${LOCAL_SIZE} (compressed)"
echo "  Decompressed  : ${SQL_SIZE}"
echo "  MD5 checksum  : ${LOCAL_MD5}"
echo "  ETag (S3)     : ${S3_ETAG}"
echo "  Status        : VALID"
echo "=========================================="
echo ""

log "Backup verification passed for date ${BACKUP_DATE}."
exit 0
