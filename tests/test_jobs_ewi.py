"""Tasks 62-64 — SSE job streaming, EWI watch service, live alerts endpoint."""
import json, os, sys, time
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pytest
from services.copilot.config import reset_settings_cache

D = lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    reset_settings_cache()
    from services.ingest_common.bus import FileBus, reset_bus
    reset_bus()
    bus = FileBus(root=str(tmp_path / "bus"))
    yield tmp_path, bus
    reset_bus()
    reset_settings_cache()


# ------------------------------------------------------------------ Task 62 --
def test_sse_job_streams_progress_then_result(env, monkeypatch):
    from fastapi.testclient import TestClient
    from services.copilot.main import app
    with TestClient(app) as c:
        r = c.post("/v1/jobs", json={
            "kind": "counterfactual",
            "interventions": ["Gulf maritime verification coalition"],
            "targets": ["ME_war_1y", "Brent_gt120_1y"],
            "horizon_quarters": 12, "n_paths": 20000, "n_batches": 5})
        assert r.status_code == 200
        jid = r.json()["job_id"]
        events, result = [], None
        with c.stream("GET", f"/v1/stream/{jid}") as s:
            cur_event = None
            for line in s.iter_lines():
                line = line.decode() if isinstance(line, bytes) else line
                if line.startswith("event:"):
                    cur_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and cur_event:
                    payload = json.loads(line.split(":", 1)[1])
                    events.append((cur_event, payload))
                    if cur_event == "result":
                        result = payload
                        break
        progress = [p for e, p in events if e == "progress"]
        assert len(progress) == 5                               # real batch progress
        assert [p["pct"] for p in progress] == [20, 40, 60, 80, 100]
        assert result and result["n_paths_total"] == 20000
        eff = {e["target"]: e for e in result["effects"]}
        assert eff["ME_war_1y"]["delta"] < 0                    # de-escalation lever
        st = c.get(f"/v1/jobs/{jid}").json()
        assert st["status"] == "done"
        # late subscriber gets the cached result immediately
        with c.stream("GET", f"/v1/stream/{jid}") as s2:
            txt = "".join(l.decode() if isinstance(l, bytes) else l
                          for l in s2.iter_lines())
        assert "event: result" in txt or "result" in txt
        assert c.post("/v1/jobs", json={"kind": "nope"}).status_code == 422
        assert c.get("/v1/jobs/unknown").status_code == 404


# ------------------------------------------------------------------ Task 63 --
def test_ewi_watch_edge_triggered(env):
    tmp_path, bus = env
    from services.ingest_common.series import SeriesStore
    from services.ingest_common.sink import RawEventSink
    from services.ewi.watch import watch_once, TOPIC_ALERTS
    ser = SeriesStore(sqlite_path=str(tmp_path / "s.db"))
    snk = RawEventSink(sqlite_path=str(tmp_path / "i.db"))
    now = D("2026-06-10")
    ser.add_points("brent_usd", [(D("2026-06-01"), 100), (D("2026-06-09"), 115)])
    evs = [{"source": "acled", "source_id": f"W{i}", "event_type": "battles",
            "actors": {"country": "Iran"}, "h3_cell": None,
            "occurred_at": now - i * 86400, "magnitude": 1, "confidence": 0.9,
            "payload": {}} for i in range(6)]
    snk.insert_many(evs)
    rep1 = watch_once(ser, snk, bus, now=now)
    fired = {a["indicator"] for a in rep1["fired"]}
    assert {"Brent level", "Brent day-jump", "Iran battle tempo"} <= fired
    assert bus.depth(TOPIC_ALERTS) == len(rep1["fired"])
    a = rep1["fired"][0]
    assert {"indicator", "severity", "value", "threshold", "message",
            "fired_at"} <= set(a)
    rep2 = watch_once(ser, snk, bus, now=now + 3600)             # still breached
    assert rep2["fired"] == [] and set(rep2["active"]) >= fired  # edge-triggered
    ser.add_points("brent_usd", [(now + 7200, 95)])              # clears level rule
    rep3 = watch_once(ser, snk, bus, now=now + 10000)
    assert "Brent level" in rep3["cleared"]


# ------------------------------------------------------------------ Task 64 --
def test_alerts_endpoint_serves_bus(env, monkeypatch):
    tmp_path, bus = env
    import services.ingest_common.bus as busmod
    monkeypatch.setattr(busmod, "_BUS", bus)                     # API reads same spool
    from services.ewi.watch import TOPIC_ALERTS
    t0 = time.time()
    bus.publish(TOPIC_ALERTS, [{"indicator": "Test", "severity": "high",
                                "value": 1, "threshold": 0, "message": "m",
                                "fired_at": t0, "source_id": "t|1"}], producer="t")
    from fastapi.testclient import TestClient
    from services.copilot.main import app
    with TestClient(app) as c:
        body = c.get("/v1/ewi/alerts").json()
        assert len(body["alerts"]) == 1
        assert body["alerts"][0]["indicator"] == "Test"
        empty = c.get("/v1/ewi/alerts", params={"since": time.time() + 60}).json()
        assert empty["alerts"] == []
