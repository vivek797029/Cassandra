"""Task 40 — store contract tests.

The same behavioral contract must hold for every backend:
  * sqlite  — always runs
  * postgres — runs when DATABASE_URL is set (compose phase2 stack, CI service);
               cleanly skipped otherwise with an actionable reason
Plus: every PgStore SQL statement is validated under the REAL PostgreSQL
grammar (pglast) — no server required, catches syntax errors at unit-test time.

Run on PG locally:
  docker compose -f deploy/docker/docker-compose.yml --profile phase2 up -d postgres
  DATABASE_URL=postgresql://argus:argus-dev-only@localhost:5432/argus \
    python -m pytest tests/test_store_contract.py tests/test_api.py -q
"""
import os, sys, time, uuid
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest

BACKENDS = ["sqlite"]
if os.environ.get("DATABASE_URL"):
    BACKENDS.append("postgres")


@pytest.fixture(params=BACKENDS)
def store(request, tmp_path):
    if request.param == "sqlite":
        from services.copilot.store import Store
        s = Store(path=str(tmp_path / "contract.db"))
        yield s
    else:
        from services.copilot.store_pg import PgStore
        s = PgStore()
        yield s
        s.close()


def test_session_idempotent(store):
    sid = store.ensure_session(None, "analyst")
    assert len(sid) == 12
    assert store.ensure_session(sid, "analyst") == sid          # no duplicate


def test_message_roundtrip_order_and_types(store):
    sid = store.ensure_session(None, "analyst")
    store.log_message(sid, "user", "first question", "FORECAST", "m-1", 5)
    time.sleep(0.01)
    store.log_message(sid, "assistant", "first answer", "FORECAST", "m-1", 7)
    msgs = store.session_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "first question"
    assert msgs[1]["latency_ms"] == 7
    assert isinstance(msgs[0]["created_at"], float)              # parity across backends
    assert msgs[0]["created_at"] <= msgs[1]["created_at"]


def test_run_upsert_and_payload_fidelity(store):
    mid = "cafe" + uuid.uuid4().hex[:12]
    payload = {"targets": ["ME_war_1y"], "mods": {"me_esc": 0.8}, "Q": 12}
    store.record_run(mid, "counterfactual", payload, "deadbeef0001", 42)
    store.record_run(mid, "counterfactual", payload, "deadbeef0002", 42)   # upsert, no error
    run = store.get_run(mid)
    assert run["kind"] == "counterfactual"
    assert run["payload"] == payload                              # JSON fidelity
    assert run["theta_hash"] == "deadbeef0002"                    # updated on conflict
    assert store.get_run("does-not-exist") is None


def test_audit_append(store):
    store.audit("tester", "contract-check", "detail text")       # must not raise


def test_answers_stats_shape(store):
    sid = store.ensure_session(None, "analyst")
    store.log_message(sid, "assistant", "an answer", "FORECAST", "m-9", 12)
    st = store.answers_stats()
    assert set(st) == {"answers_total", "avg_latency_ms"}
    assert st["answers_total"] >= 1 and isinstance(st["avg_latency_ms"], float)


def test_message_truncation(store):
    sid = store.ensure_session(None, "analyst")
    store.log_message(sid, "user", "x" * 20000)
    msgs = store.session_messages(sid)
    assert len(msgs[-1]["content"]) <= 8000                       # 8k cap both backends


# ---------------------------------------------------------------------------
# PG-grammar validation of every driver statement (runs WITHOUT a server)
# ---------------------------------------------------------------------------
def test_pg_driver_sql_parses_under_postgres_grammar():
    pglast = pytest.importorskip("pglast")
    from services.copilot.store_pg import SQL
    for name, stmt in SQL.items():
        parseable = stmt.replace("%s", "NULL")    # placeholder -> literal for grammar
        try:
            pglast.parse_sql(parseable)
        except Exception as ex:                   # pragma: no cover
            pytest.fail(f"SQL['{name}'] rejected by PostgreSQL grammar: {ex}")
