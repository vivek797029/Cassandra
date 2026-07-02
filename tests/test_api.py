"""Copilot API tests — run: python3 -m pytest tests/test_api.py -q (from repo root)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/test_copilot.db")

import pytest
from fastapi.testclient import TestClient
from services.copilot.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_health(client):
    assert client.get("/healthz").json()["status"] == "ok"
    r = client.get("/readyz").json()
    assert r["status"] == "ready" and len(r["theta_hash"]) == 12

def test_forecasts_list(client):
    fs = client.get("/v1/forecasts").json()
    assert len(fs) >= 12
    for f in fs:
        assert 0.0 <= f["probability"] <= 1.0
        if f["band"]:
            assert f["band"]["lo"] <= f["probability"] <= f["band"]["hi"]

def test_forecast_known_and_unknown(client):
    assert client.get("/v1/forecasts/ME_war_1y").status_code == 200
    assert client.get("/v1/forecasts/NOT_A_KEY").status_code == 404

def test_ask_forecast_grounded(client):
    j = client.post("/v1/ask", json={"text": "What's the chance of a global recession?"}).json()
    assert j["intent"] == "FORECAST" and not j["abstained"]
    assert j["forecasts"] and "recession" in j["answer_markdown"].lower() or "growth" in j["answer_markdown"].lower()
    assert j["manifest_id"]

def test_ask_whatif_runs_paired_cf(client):
    j = client.post("/v1/ask", json={
        "text": "What if we deploy a Gulf maritime verification coalition?"}).json()
    assert j["intent"] == "WHATIF" and j["counterfactual"]
    eff = {e["target"]: e for e in j["counterfactual"]["effects"]}
    assert eff["ME_war_1y"]["delta"] < 0          # de-escalation lever lowers war prob
    assert j["counterfactual"]["harm_counterfactual"] <= j["counterfactual"]["harm_baseline"]

def test_ask_policy(client):
    j = client.post("/v1/ask", json={"text": "Which policy reduces risk best with budget 8?"}).json()
    assert j["intent"] == "POLICY" and j["policy"]["harm_reduction_pct"] > 0
    assert j["policy"]["spent"] <= j["policy"]["budget"]

def test_ask_abstains_off_grammar(client):
    j = client.post("/v1/ask", json={"text": "What's the weather like?"}).json()
    assert j["abstained"] is True

def test_counterfactual_endpoint_reproducible(client):
    body = {"do": {"interventions": ["EM bridge-financing window"], "hazard_mods": {}},
            "targets": ["EM_default_quarters_ge3_by_2028"], "horizon_quarters": 12, "n_paths": 1500}
    a = client.post("/v1/counterfactual", json=body).json()
    b = client.post("/v1/counterfactual", json=body).json()
    assert a["manifest_id"] == b["manifest_id"]                 # deterministic manifest
    assert a["effects"] == b["effects"]                          # CRN determinism
    assert a["effects"][0]["delta"] < 0

def test_audit_roundtrip(client):
    j = client.post("/v1/ask", json={"text": "what if we use the food security facility"}).json()
    mid = j["manifest_id"]
    run = client.get(f"/v1/audit/{mid}").json()
    assert run["manifest_id"] == mid and run["kind"] == "counterfactual"

def test_session_memory(client):
    j1 = client.post("/v1/ask", json={"text": "will democrats take the house?"}).json()
    sid = j1["session_id"]
    j2 = client.post("/v1/ask", json={"text": "show me the scenarios", "session_id": sid}).json()
    assert j2["session_id"] == sid
    msgs = client.get(f"/v1/sessions/{sid}").json()
    assert len(msgs) >= 4 and msgs[0]["role"] == "user"

def test_ewi_analogs_scenarios(client):
    assert len(client.get("/v1/ewi").json()) == 10
    assert len(client.get("/v1/analogs").json()) == 5
    sc = client.get("/v1/scenarios").json()
    assert abs(sum(c["share"] for c in sc["clusters"]) - 1) < 0.01

def test_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "ARGUS" in r.text
