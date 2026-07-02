"""Tasks 49+50+51 — the learning loop end-to-end:
retro generation (snapshots+leakage) -> resolution -> scoring -> registry training."""
import json, os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import reset_settings_cache
from services.copilot.store import Store
from services.ingest_common.sink import RawEventSink
from services.ingest_common.series import SeriesStore
from services.question_registry.registry import QuestionRegistry
from services.question_registry import resolver
from scripts.gen_retro_questions import generate, leakage_check
from workers.score import record_predictions, score

D = lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
NOW = D("2026-06-11")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    reset_settings_cache()
    reg = QuestionRegistry(sqlite_path=str(tmp_path / "r.db"))
    sink = RawEventSink(sqlite_path=str(tmp_path / "i.db"))
    ser = SeriesStore(sqlite_path=str(tmp_path / "s.db"))
    store = Store(path=str(tmp_path / "c.db"))
    # brent history mirroring the real Feb-Jun 2026 shock: 80 -> spike 125 -> 94
    pts = [("2026-01-05", 80), ("2026-01-19", 81), ("2026-02-02", 82),
           ("2026-02-16", 84), ("2026-03-02", 105), ("2026-03-16", 122),
           ("2026-03-30", 125), ("2026-04-13", 118), ("2026-04-27", 104),
           ("2026-05-11", 99), ("2026-05-25", 95), ("2026-06-08", 94)]
    ser.add_points("brent_usd", [(D(d), v) for d, v in pts])
    # ACLED battle history for event_count family
    evs = [{"source": "acled", "source_id": f"L{i}", "event_type": "battles",
            "actors": {"country": "Iran"}, "h3_cell": "g5:35.5,51.5",
            "occurred_at": D("2026-02-28") + i * 2 * 86400, "magnitude": 1,
            "confidence": 0.9, "payload": {}} for i in range(30)]
    sink.insert_many(evs)
    yield reg, sink, ser, store
    for x in (reg, sink, ser):
        x.close()
    reset_settings_cache()


def gen(reg, sink, ser, n=300):
    return generate(reg, ser, sink, n_target=n, start="2026-01-05", end="2026-03-30",
                    ec_sources=[("acled", "battles", "Iran")])


# ------------------------------------------------------------------ Task 49 --
def test_generator_200_questions_with_snapshots(env):
    reg, sink, ser, _ = env
    rep = gen(reg, sink, ser)
    assert rep["created"] >= 200
    rep2 = gen(reg, sink, ser)                                  # idempotent
    assert rep2["created"] == 0 and rep2["skipped_existing"] >= 200
    qs = [q for q in reg.list() if q["key"].startswith("retro_")]
    rule = json.loads(qs[0]["resolution_rule"])
    assert "snapshot" in rule and rule["from"] == rule["snapshot"]["asof"]


def test_leakage_check_passes_and_catches_corruption(env):
    reg, sink, ser, _ = env
    gen(reg, sink, ser)
    rep = leakage_check(reg, ser, sink)
    assert rep["passed"] and rep["checked"] >= 200
    # corrupt one snapshot (simulate a generator that peeked at the future)
    q = next(x for x in reg.list() if x["key"].startswith("retro_brent"))
    rule = json.loads(q["resolution_rule"])
    rule["snapshot"]["value_asof"] = 999.0
    reg.conn.execute("UPDATE questions SET resolution_rule=? WHERE key=?",
                     (json.dumps(rule), q["key"]))
    reg.conn.commit()
    rep2 = leakage_check(reg, ser, sink)
    assert not rep2["passed"]
    assert any(v["key"] == q["key"] and v["why"] == "snapshot mismatch"
               for v in rep2["violations"])


def test_resolution_yields_mixed_outcomes(env):
    reg, sink, ser, _ = env
    gen(reg, sink, ser)
    rep = resolver.resolve_pending(reg, sink, ser, now=NOW)
    resolved = rep["resolved_yes"] + rep["resolved_no"]
    assert resolved >= 150                                       # deadlines mostly past
    yes_rate = rep["resolved_yes"] / resolved
    assert 0.15 <= yes_rate <= 0.85, yes_rate                    # non-degenerate dataset


# ------------------------------------------------------------------ Task 50 --
def test_scoring_job_brier_log_strata_bins(env):
    reg, sink, ser, store = env
    gen(reg, sink, ser)
    resolver.resolve_pending(reg, sink, ser, now=NOW)
    resolved = reg.list(resolved=True)
    # hand-checkable predictions: confident-right on half, climatology on rest
    preds = []
    for i, q in enumerate(resolved):
        p = (0.9 if q["outcome"] == 1 else 0.1) if i % 2 == 0 else 0.5
        preds.append({"key": q["key"], "probability": p})
    assert record_predictions(store, preds, "testtheta0001") == len(resolved)
    rep = score(store, reg)
    assert rep["n_scored"] == len(resolved)
    # exact Brier: half scored (p=.9/.1 -> .01), half at .25
    expect = (0.01 * ((len(resolved) + 1) // 2) + 0.25 * (len(resolved) // 2)) / len(resolved)
    assert abs(rep["brier"] - expect) < 0.001
    assert rep["brier_skill_score"] > 0                          # beats climatology
    assert any("economic|" in k for k in rep["by_stratum"])      # strata grouped
    assert rep["reliability_bins"] and rep["ece"] is not None
    run = store.get_run(rep["manifest_id"])                      # persisted run record
    assert run and run["payload"]["job"] == "scoring"


# ------------------------------------------------------------------ Task 51 --
def test_trainer_on_registry_events_brier_not_worse(env):
    reg, sink, ser, _ = env
    gen(reg, sink, ser)
    resolver.resolve_pending(reg, sink, ser, now=NOW)
    from novelty.cassandra import (load_registry_events, rolling_split,
                                   CalibrationTrainer, brier)
    from core.engine import WorldEngine, THETA_DEFAULT, replay_event_probs
    events, meta, req_q = load_registry_events(reg)
    assert len(events) >= 60 and req_q >= 2                      # real training set
    outs = [o for _, o, _ in events]
    assert 0 < sum(outs) < len(outs)                             # mixed outcomes
    train, evl = rolling_split(events, meta, "2026-04-01")       # rolling-origin
    assert train and evl
    tr = CalibrationTrainer(n_paths=800, events=train, replay_Q=req_q)
    p0, y0 = replay_event_probs(WorldEngine(THETA_DEFAULT), N=800, seed=7,
                                events=train, Q=req_q)
    b0 = brier(p0, y0)
    theta = tr.train(iters=8, verbose=False)
    p1, _ = replay_event_probs(WorldEngine(theta), N=800, seed=7,
                               events=train, Q=req_q)
    b1 = brier(p1, y0)
    assert b1 <= b0 + 0.01, (b0, b1)                             # acceptance gate
    # held-out rolling-origin eval also computable
    pe, ye = replay_event_probs(WorldEngine(theta), N=800, seed=7,
                                events=evl, Q=req_q)
    assert 0 <= brier(pe, ye) <= 1
