#!/usr/bin/env bash
# clean-duplicate-files.sh
#
# Removes macOS Finder / iCloud "duplicate" artifacts that match the pattern
#   <name> <digit>.<ext>     (files,  e.g. "foo 2.py", "report 3.md")
#   <name> <digit>           (dirs,   e.g. "components 2/")
#
# These are generated automatically by macOS Finder, iCloud Drive sync
# conflicts, or Time Machine — never by humans. They never belong in the repo.
#
# Usage:
#   bash scripts/clean-duplicate-files.sh [--dry-run] [--root <path>]
#
# Environment variables:
#   DRY_RUN=true|false   (default: false)
#   ROOT_DIR=<path>      (default: repo root, derived from git)

set -euo pipefail

DRY_RUN="${DRY_RUN:-false}"
ROOT_DIR="${ROOT_DIR:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN="true"; shift ;;
    --root)    ROOT_DIR="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$ROOT_DIR" ]]; then
  ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi

if [[ ! -d "$ROOT_DIR" ]]; then
  echo "Root directory not found: $ROOT_DIR" >&2
  exit 1
fi

cd "$ROOT_DIR"

# Directories we never traverse (large, generated, virtual envs, or out of
# scope for cleanup — caches will regenerate themselves).
PRUNE_EXPR=(
  -path './.git' -o
  -path './.venv' -o
  -path './venv' -o
  -path './.mypy_cache' -o
  -path './.pytest_cache' -o
  -path './.ruff_cache' -o
  -path './__pycache__' -o
  -path '*/__pycache__' -o
  -path './node_modules' -o
  -path './_worktrees' -o
  -path './coverage' -o
  -path './htmlcov' -o
  -path './dist' -o
  -path './build'
)

# Find duplicate FILES: ' <digit>.<ext>'
mapfile -t DUP_FILES < <(
  find . \( "${PRUNE_EXPR[@]}" \) -prune -o -type f -print 2>/dev/null \
    | grep -E ' [0-9]+\.[a-zA-Z0-9]+$' \
    | sort
)

# Find duplicate DIRECTORIES: ' <digit>$'
mapfile -t DUP_DIRS < <(
  find . \( "${PRUNE_EXPR[@]}" \) -prune -o -type d -print 2>/dev/null \
    | grep -E ' [0-9]+$' \
    | sort
)

TOTAL=$(( ${#DUP_FILES[@]} + ${#DUP_DIRS[@]} ))

if [[ $TOTAL -eq 0 ]]; then
  echo "No duplicate artifacts found under $ROOT_DIR"
  exit 0
fi

echo "Scanning $ROOT_DIR"
echo "  Duplicate files:       ${#DUP_FILES[@]}"
echo "  Duplicate directories: ${#DUP_DIRS[@]}"
echo

if [[ ${#DUP_FILES[@]} -gt 0 ]]; then
  echo "Files:"
  printf '  %s\n' "${DUP_FILES[@]}"
  echo
fi

if [[ ${#DUP_DIRS[@]} -gt 0 ]]; then
  echo "Directories:"
  printf '  %s\n' "${DUP_DIRS[@]}"
  echo
fi

if [[ "$DRY_RUN" == "true" ]]; then
  echo "Dry-run mode — no changes made. Run without --dry-run to delete."
  exit 0
fi

# Refuse to proceed if any of the targets are git-tracked. Tracked artifacts
# may be intentional and should be removed via a real commit, not a janitor.
TRACKED=()
for path in "${DUP_FILES[@]}" "${DUP_DIRS[@]}"; do
  if git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
    TRACKED+=("$path")
  fi
done

if [[ ${#TRACKED[@]} -gt 0 ]]; then
  echo "Refusing to delete: the following paths are git-tracked." >&2
  printf '  %s\n' "${TRACKED[@]}" >&2
  echo "Remove them via 'git rm' in a real commit if intentional." >&2
  exit 1
fi

# Remove directories first (so their files do not re-appear in the file list
# of subsequent runs), then files.
for dir in "${DUP_DIRS[@]}"; do
  rm -rf -- "$dir"
  echo "removed dir:  $dir"
done

for file in "${DUP_FILES[@]}"; do
  rm -f -- "$file"
  echo "removed file: $file"
done

echo
echo "Cleanup complete: $TOTAL artifact(s) removed."
