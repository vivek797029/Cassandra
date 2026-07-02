"""Task 48 — resolver v1 tests, incl. the acceptance gate: 20 retro questions auto-resolve."""
import os, sys, time
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import reset_settings_cache
from services.ingest_common.sink import RawEventSink
from services.ingest_common.series import SeriesStore
from services.question_registry.registry import QuestionRegistry
from services.question_registry import resolver

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
    # brent ramp: 80 -> 130 over Jan-May 2026 (daily-ish, 11 points)
    ser.add_points("brent_usd", [(D(f"2026-0{m}-{d:02d}"), v) for (m, d, v) in [
        (1, 5, 80), (1, 20, 85), (2, 5, 90), (2, 20, 96), (3, 5, 102),
        (3, 20, 108), (4, 5, 114), (4, 20, 119), (5, 5, 124), (5, 20, 128), (5, 30, 130)]])
    # ACLED battle cluster: 8 events in 5 days (Mar 1-5), Iran; +2 in Egypt
    evs = [{"source": "acled", "source_id": f"R{i}", "event_type": "battles",
            "actors": {"a1": "X", "country": "Iran"}, "h3_cell": "g5:35.5,51.5",
            "occurred_at": D("2026-03-01") + i * 0.6 * 86400, "magnitude": 1,
            "confidence": 0.9, "payload": {}} for i in range(8)]
    evs += [{"source": "acled", "source_id": f"E{i}", "event_type": "battles",
             "actors": {"country": "Egypt"}, "h3_cell": None,
             "occurred_at": D("2026-03-02"), "magnitude": 0, "confidence": 0.6,
             "payload": {}} for i in range(2)]
    sink.insert_many(evs)
    yield reg, sink, ser
    for x in (reg, sink, ser):
        x.close()
    reset_settings_cache()


def run(reg, sink, ser):
    return resolver.resolve_pending(reg, sink, ser, now=NOW)


def test_series_threshold_yes_no_pending(env):
    reg, sink, ser = env
    reg.create("s_yes", "crossed?", "economic", resolution_rule={
        "type": "series_threshold", "series": "brent_usd", "op": ">", "value": 100,
        "by": "2026-06-01"})
    reg.create("s_no", "never?", "economic", resolution_rule={
        "type": "series_threshold", "series": "brent_usd", "op": ">", "value": 200,
        "by": "2026-06-01"})
    reg.create("s_pend", "future?", "economic", resolution_rule={
        "type": "series_threshold", "series": "brent_usd", "op": ">", "value": 200,
        "by": "2027-06-01"})
    rep = run(reg, sink, ser)
    assert rep["resolved_yes"] == 1 and rep["resolved_no"] == 1 and rep["pending"] == 1
    assert reg.get("s_yes")["outcome"] == 1 and reg.get("s_no")["outcome"] == 0
    assert reg.get("s_pend")["resolved"] is False
    d = {x["key"]: x for x in rep["details"]}
    assert d["s_yes"]["evidence"]["crossing_ts"] == D("2026-03-05")   # first >100 point


def test_event_count_window_and_country_filter(env):
    reg, sink, ser = env
    base = {"type": "event_count", "source": "acled", "event_types": ["battles"],
            "countries": ["Iran"], "window_days": 7, "op": ">=", "by": "2026-06-01"}
    reg.create("e_yes", "8 in window?", "security", resolution_rule={**base, "threshold": 8})
    reg.create("e_no", "9 in window?", "security", resolution_rule={**base, "threshold": 9})
    rep = run(reg, sink, ser)
    d = {x["key"]: x for x in rep["details"]}
    assert d["e_yes"]["status"] == "resolved:1"
    assert d["e_yes"]["evidence"]["max_window_count"] == 8        # Egypt events filtered out
    assert d["e_no"]["status"] == "resolved:0"


def test_manual_untouched_and_idempotent(env):
    reg, sink, ser = env
    reg.create("m1", "manual?", "political", resolution_rule={"type": "manual"})
    reg.create("s1", "auto?", "economic", resolution_rule={
        "type": "series_threshold", "series": "brent_usd", "op": ">", "value": 90,
        "by": "2026-06-01"})
    r1 = run(reg, sink, ser)
    assert r1["manual_or_unknown"] == 1 and r1["resolved_yes"] == 1
    r2 = run(reg, sink, ser)                                       # resolved skipped
    assert r2["checked"] == 1 and r2["resolved_yes"] == 0          # only manual remains


def test_twenty_retro_questions_auto_resolve(env):
    """BUILD_PLAN acceptance: 20 retro questions auto-resolve with correct outcomes."""
    reg, sink, ser = env
    expected = {}
    for i, thr in enumerate([85, 90, 95, 100, 105, 110, 115, 120, 125, 130]):
        key = f"retro_brent_gt{thr}"
        reg.create(key, f"Brent > {thr}?", "economic", resolution_rule={
            "type": "series_threshold", "series": "brent_usd", "op": ">",
            "value": thr, "by": "2026-06-05"})
        expected[key] = 1 if thr < 130 else 0                      # ramp max 130, strict >
    for k in range(1, 11):
        key = f"retro_battles_ge{k}"
        reg.create(key, f">={k} battles in 7d?", "security", resolution_rule={
            "type": "event_count", "source": "acled", "event_types": ["battles"],
            "countries": ["Iran"], "window_days": 7, "op": ">=", "threshold": k,
            "by": "2026-06-05"})
        expected[key] = 1 if k <= 8 else 0                         # cluster of 8
    rep = run(reg, sink, ser)
    assert rep["resolved_yes"] + rep["resolved_no"] == 20
    for key, want in expected.items():
        got = reg.get(key)
        assert got["resolved"] is True and got["outcome"] == want, (key, want, got["outcome"])
    yes = sum(expected.values())
    assert rep["resolved_yes"] == yes and rep["resolved_no"] == 20 - yes


def test_resolver_api_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "api.db"))
    reset_settings_cache()
    from services.question_registry import api as qapi
    qapi.reset_registry()
    from fastapi.testclient import TestClient
    from services.copilot.main import app
    with TestClient(app) as c:
        r = c.post("/v1/questions/resolver/run")
        assert r.status_code == 200
        body = r.json()
        assert {"checked", "resolved_yes", "resolved_no", "pending",
                "manual_or_unknown"} <= set(body)
        assert body["checked"] >= 16                                # seeded engine questions
    qapi.reset_registry()
    reset_settings_cache()
