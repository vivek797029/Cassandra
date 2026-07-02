#!/usr/bin/env bash
# Task 73 — cut a release. Runs every Phase-2 exit gate; on pass, tags v$VERSION
# (annotated) when the tree is a git repo. `--check` runs the gates without tagging.
#
#   scripts/cut_release.sh            # gates + tag
#   scripts/cut_release.sh --check    # gates only
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="$(tr -d '[:space:]' < VERSION)"
PY="${PYTHON:-python3}"
export ARGUS_FAST=1
export ARGUS_DB="${ARGUS_DB:-/tmp/argus/release.db}"
mkdir -p "$(dirname "$ARGUS_DB")"; rm -f "${ARGUS_DB}"*

echo "================= ARGUS release gate — v${VERSION} ================="

echo "[1/6] engine smoke";          "$PY" tests/test_smoke.py >/dev/null && echo "  ok"
echo "[2/6] full test suite";        "$PY" -m pytest tests/ -q -p no:cacheprovider -o cache_dir=/tmp/pc >/dev/null && echo "  ok"
echo "[3/6] latency SLO gate";       "$PY" benchmarks/bench_api.py >/dev/null && echo "  ok"
echo "[4/6] red-team gates";         "$PY" -m pytest tests/redteam -q -p no:cacheprovider -o cache_dir=/tmp/pc >/dev/null && echo "  ok"
echo "[5/6] NLU contamination gate"; "$PY" -m services.copilot.nlu --gate >/dev/null && echo "  ok"
echo "[6/6] OpenAPI drift gate";     "$PY" scripts/export_openapi.py --check >/dev/null && echo "  ok"

# Optional: load test (needs locust; runs as its own CI 'loadtest' job otherwise)
if "$PY" -c "import locust" >/dev/null 2>&1; then
  echo "[+]   locust load test";     "$PY" benchmarks/run_locust.py >/dev/null && echo "  ok"
else
  echo "[+]   locust not installed — load gate runs in CI 'loadtest' job (skipped here)"
fi

echo "===================================================================="
echo "ALL EXIT GATES PASS for v${VERSION}"

if [ "${1:-}" = "--check" ]; then
  exit 0
fi

if git rev-parse --git-dir >/dev/null 2>&1; then
  git tag -a "v${VERSION}" -m "ARGUS v${VERSION} — Phase-2 exit (tasks 39–72)"
  echo "tagged v${VERSION}"
else
  echo "not a git repo — to create the tag:"
  echo "  git init && git add -A && git commit -m 'ARGUS v${VERSION} — Phase-2 exit'"
  echo "  git tag -a v${VERSION} -m 'ARGUS v${VERSION} — Phase-2 exit (tasks 39–72)'"
fi
