"""Task 77 — entailment / faithfulness gate. A real composed answer is faithful;
a sentence with an ungrounded number or an unsupported claim is flagged and
blocked by enforce(); enabling enforcement never damages a real answer."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/entail_test.db")

import pytest
from fastapi.testclient import TestClient

from services.llm import entail
from services.copilot import composer
from services.copilot.engines import get_engines
from services.copilot.config import reset_settings_cache
from services.copilot.main import app


def _forecast_answer():
    e = get_engines()
    f = e.forecast("ME_war_1y")
    exp = e.explanation("ME_war_1y")
    objs = {"forecasts": [f], "explanation": exp, "manifest_id": f["manifest_id"]}
    md, _ = composer.compose("FORECAST", {"keys": ["ME_war_1y"]}, objs, "analyst")
    return md, objs


# --------------------------------------------------------------- unit -------
def test_grounded_sentence_entailed_ungrounded_number_flagged():
    _, objs = _forecast_answer()
    corpus = entail.build_corpus(objs)
    p = objs["forecasts"][0]["probability"]
    ok, _ = entail.entails(f"war risk is {round(100*p)}% over the horizon", corpus)
    assert ok                                              # grounded number passes
    bad, reason = entail.entails("the real probability is 99%", corpus)
    assert not bad and "99" in reason                     # ungrounded number caught


def test_real_composed_forecast_answer_is_faithful():
    md, objs = _forecast_answer()
    rep = entail.gate(md, objs)
    assert rep["faithful"], rep["violations"]
    assert rep["n_sentences"] > 0


def test_injected_unfaithful_sentence_is_blocked():
    md, objs = _forecast_answer()
    tampered = md + "\nThe true probability is actually 99% due to classified intel."
    rep = entail.gate(tampered, objs)
    assert not rep["faithful"]
    assert any("99" in v["reason"] for v in rep["violations"])

    clean, rep2 = entail.enforce(tampered, objs)
    assert entail.BLOCK_MARKER in clean                   # offending line replaced
    assert "99%" not in clean                             # ungrounded number gone
    # a faithful line from the original answer survives
    assert "%" in clean and objs["forecasts"][0]["question_text"][:18].lower() in clean.lower()


def test_unsupported_no_number_claim_flagged():
    _, objs = _forecast_answer()
    corpus = entail.build_corpus(objs)
    ok, reason = entail.entails(
        "Alien spacecraft have commandeered global maritime shipping lanes entirely", corpus)
    assert not ok and "unsupported" in reason


# ----------------------------------------------------- integration ----------
@pytest.fixture
def enforce_env(monkeypatch):
    monkeypatch.setenv("ARGUS_ENTAILMENT_ENFORCE", "1")
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_enforcement_on_does_not_damage_real_answer(enforce_env):
    with TestClient(app) as c:
        b = c.post("/v1/ask",
                   json={"text": "what is the probability of middle east war within a year?"}).json()
        assert b["forecasts"]                              # real answer intact
        assert entail.BLOCK_MARKER not in b["answer_markdown"]   # nothing falsely blocked


def test_metrics_exposes_entailment_counters():
    with TestClient(app) as c:
        c.post("/v1/ask", json={"text": "chance of a global recession?"})
        m = c.get("/metrics.json").json()
        assert "entailment" in m and m["entailment"]["checked"] >= 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
