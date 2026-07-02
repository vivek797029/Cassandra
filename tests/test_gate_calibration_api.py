"""Tasks 57+60 — mechanism id-status gate and the /v1/calibration endpoint."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
import pytest
from services.copilot.config import reset_settings_cache


# ------------------------------------------------------------------ Task 57 --
def test_gate_passes_allowed_and_blocks_hypothesis():
    from services.kg.gate import gate_theta
    from services.kg.mechanisms import MECHANISM_CARDS
    from core.engine import THETA_DEFAULT, THETA_NAMES
    trained = THETA_DEFAULT * 1.5                       # every param deviates
    gated, rep = gate_theta(trained)
    assert rep["blocked"] == []                          # no hypothesis cards shipped
    assert np.allclose(gated, trained)                   # allowed params untouched
    assert set(rep["estimated_flagged"]) == {"oil_pass_infl", "oil_drag_growth"}
    assert rep["uncarded"] == []                         # every theta param is carded
    # downgrade one card to hypothesis -> its params must revert to prior
    cards = json.loads(json.dumps(MECHANISM_CARDS))
    next(c for c in cards if c["id"] == "oil__inflation")["id_status"] = "hypothesis"
    gated2, rep2 = gate_theta(trained, cards=cards)
    i = THETA_NAMES.index("oil_pass_infl")
    assert gated2[i] == THETA_DEFAULT[i]                 # reverted
    assert rep2["blocked"][0]["param"] == "oil_pass_infl"
    assert rep2["blocked"][0]["mechanism"] == "oil__inflation"
    j = THETA_NAMES.index("oil_jump_war")
    assert gated2[j] == trained[j]                       # identified still passes


def test_every_theta_param_has_a_mechanism_card():
    from services.kg.mechanisms import card_for_param
    from core.engine import THETA_NAMES
    missing = [n for n in THETA_NAMES if card_for_param(n) is None]
    assert missing == [], f"uncarded params: {missing}"


def test_mechanisms_endpoint(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    reset_settings_cache()
    from fastapi.testclient import TestClient
    from services.copilot.main import app
    with TestClient(app) as c:
        v = c.get("/v1/mechanisms").json()
        assert len(v["cards"]) == 7
        assert v["gate_report_on_live_theta"]["blocked"] == []
        assert "hypothesis" not in v["allowed_statuses"]
    reset_settings_cache()


# ------------------------------------------------------------------ Task 60 --
def test_calibration_endpoint_matches_scoring_job(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    reset_settings_cache()
    import services.copilot.store as storemod
    storemod.STORE = None
    from workers import score as scoremod
    # isolate the report file so we exercise the computed-live path first
    monkeypatch.setattr(scoremod, "OUT_JSON", str(tmp_path / "calibration.json"))
    import services.copilot.main as mainmod
    from services.question_registry import api as qapi
    qapi.reset_registry()
    from fastapi.testclient import TestClient
    with TestClient(mainmod.app) as c:
        # seed: resolve two questions and record predictions
        c.post("/v1/questions", json={"key": "cal_a", "text": "A?", "domain": "economic",
                                      "horizon": "30d"})
        c.post("/v1/questions", json={"key": "cal_b", "text": "B?", "domain": "economic",
                                      "horizon": "30d"})
        c.post("/v1/questions/cal_a/resolve", json={"outcome": 1})
        c.post("/v1/questions/cal_b/resolve", json={"outcome": 0})
        st = storemod.get_store()
        scoremod.record_predictions(st, [{"key": "cal_a", "probability": 0.8},
                                         {"key": "cal_b", "probability": 0.3}], "t0001")
        # patch the endpoint's view of OUT_JSON via module attr used inside handler
        monkeypatch.setattr("workers.score.OUT_JSON", str(tmp_path / "calibration.json"))
        rep = c.get("/v1/calibration").json()
        assert rep["n_scored"] == 2
        expect_brier = ((0.8 - 1) ** 2 + (0.3 - 0) ** 2) / 2          # 0.065
        assert abs(rep["brier"] - expect_brier) < 1e-6
        assert rep["by_stratum"]["economic|30d"]["n"] == 2
        assert rep["source"] == "computed-live"
        rep2 = c.get("/v1/calibration").json()                        # now file-backed
        assert rep2["source"] == "last-scoring-run"
        assert rep2["brier"] == rep["brier"]                          # JSON matches scores
    qapi.reset_registry()
    storemod.STORE = None
    reset_settings_cache()
