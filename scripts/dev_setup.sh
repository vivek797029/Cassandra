#!/usr/bin/env bash
# Reproducible local dev/test environment for ARGUS Copilot.
# Creates .venv with all runtime + test + load-test deps (incl. locust's gevent extras),
# then runs the suite. One command to go from a clean checkout to green.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q \
  -r requirements.txt -r requirements-api.txt -r requirements-ingest.txt -r requirements-bench.txt
# test-only extras: pytest, PG SQL grammar check (pglast), postgres driver, gevent's zope deps
.venv/bin/pip install -q pytest pglast "psycopg[binary]>=3.2" "zope.event" "zope.interface"

echo "== environment ready (.venv) =="
export ARGUS_FAST=1 ARGUS_DB=/tmp/argus/dev.db
mkdir -p /tmp/argus
.venv/bin/python -m pytest tests/ -q
echo
echo "Next:"
echo "  .venv/bin/python -m uvicorn services.copilot.main:app --port 8000   # run the API"
echo "  .venv/bin/python benchmarks/run_locust.py                            # load gate"
echo "  scripts/cut_release.sh --check                                       # full release gate"
