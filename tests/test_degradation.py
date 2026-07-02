"""Task 70 — graceful degradation chaos test.

Warm the API (which persists a last-known-good snapshot), then simulate the
forecasting engine crashing by making get_engines() raise. The service must:
  * stay alive (/healthz 200) and report /readyz degraded (503, not a hang);
  * keep serving cached reads (/v1/forecasts, /v1/ewi, /v1/fans) with an
    X-Argus-Degraded header and the SAME numbers as the live snapshot;
  * answer /v1/ask read intents from the snapshot with a staleness banner;
  * refuse live simulation honestly (/v1/ask what-if abstains; /v1/counterfactual
    and /v1/policy/optimize return 503) — never a 500;
  * fully recover once the engine is back.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

os.environ.setdefault("ARGUS_FAST", "1")
os.environ["ARGUS_DB"] = os.path.join(tempfile.gettempdir(), "argus_degrade_test.db")
os.environ["ARGUS_SNAPSHOT"] = os.path.join(tempfile.gettempdir(), "argus_degrade_snapshot.json")

import pytest
from fastapi.testclient import TestClient
from services.copilot import main

REC = "Global_recession_lt2p5_by_2028"


@pytest.fixture(autouse=True)
def _fresh_snapshot():
    for p in (os.environ["ARGUS_SNAPSHOT"], os.environ["ARGUS_DB"]):
        try:
            os.remove(p)
        except OSError:
            pass
    yield


def test_engine_down_serves_cached_with_staleness_then_recovers(monkeypatch):
    with TestClient(main.app) as c:          # startup warms engine + saves snapshot
        # ---- healthy baseline ----
        assert c.get("/readyz").json()["status"] == "ready"
        live = c.get(f"/v1/forecasts/{REC}").json()
        live_prob = live["probability"]
        live_all = {f["key"] for f in c.get("/v1/forecasts").json()}
        r_live = c.post("/v1/ask", json={"text": "what is the probability of a global recession?"})
        assert r_live.json()["degraded"] is False

        # ---- chaos: the engine goes down ----
        orig = main.get_engines

        def _down(*a, **k):
            raise RuntimeError("simulated engine crash")

        monkeypatch.setattr(main, "get_engines", _down)

        # liveness stays up; readiness reports degraded (503, not a hang/500)
        assert c.get("/healthz").status_code == 200
        rz = c.get("/readyz")
        assert rz.status_code == 503
        assert rz.json()["degraded"] is True and rz.json()["snapshot"] is not None

        # cached reads still served, flagged stale, identical numbers
        rf = c.get("/v1/forecasts")
        assert rf.status_code == 200
        assert rf.headers.get("X-Argus-Degraded") == "1"
        assert {f["key"] for f in rf.json()} == live_all
        one = c.get(f"/v1/forecasts/{REC}")
        assert one.status_code == 200 and one.json()["probability"] == live_prob
        assert c.get("/v1/ewi").status_code == 200
        assert c.get("/v1/fans").status_code == 200

        # /v1/ask read intent → cached answer + staleness banner, same number
        rd = c.post("/v1/ask", json={"text": "what is the probability of a global recession?"})
        assert rd.status_code == 200
        body = rd.json()
        assert body["degraded"] is True and body["staleness"] is not None
        assert "degraded mode" in body["answer_markdown"].lower()
        assert body["forecasts"] and body["forecasts"][0]["probability"] == live_prob

        # /v1/ask live-compute intent → honest abstain, never 500
        rw = c.post("/v1/ask", json={"text": "what if we deploy a Gulf maritime coalition?"})
        assert rw.status_code == 200
        assert rw.json()["degraded"] is True and rw.json()["abstained"] is True
        assert rw.json()["counterfactual"] is None

        # live-compute endpoints → clean 503 (not 500)
        assert c.post("/v1/counterfactual",
                      json={"do": {"interventions": ["Gulf maritime verification coalition"]},
                            "targets": [REC]}).status_code == 503
        assert c.post("/v1/policy/optimize", params={"budget": 8}).status_code == 503

        # ---- recovery ----
        monkeypatch.setattr(main, "get_engines", orig)
        assert c.get("/readyz").json()["status"] == "ready"
        rec = c.post("/v1/ask", json={"text": "what is the probability of a global recession?"})
        assert rec.json()["degraded"] is False
        assert "X-Argus-Degraded" not in c.get("/v1/forecasts").headers


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
