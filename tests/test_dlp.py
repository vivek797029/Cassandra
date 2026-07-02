"""Task 91 — DLP export gates: classification banners, seeded canaries, and
withheld-fact terms are detected and blocked before a summary egresses."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/dlp_test.db")

import pytest
from fastapi.testclient import TestClient
from services.gateway import dlp
from services.copilot.config import reset_settings_cache
from services.copilot.main import app


def test_scan_flags_classification_banners():
    f = dlp.scan("Situation update TS//SI/TK //NOFORN — Brent rising.")
    types = {x["type"] for x in f}
    assert "classification-banner" in types
    assert dlp.scan("plain grounded forecast: 58% [56%-61%]") == []


def test_seeded_canary_is_blocked():
    canary = "ZZLEAK-CANARY-7f3a"
    summary = f"Routine answer. {canary} appears here."
    assert any(x["type"] == "canary" for x in dlp.scan(summary, canaries=[canary]))
    clean, findings = dlp.enforce(summary, canaries=[canary])
    assert canary not in clean and dlp.REDACTION in clean and findings


def test_withheld_classified_term_blocked_on_export():
    secret_fact = "Operation Epic Fury killed Supreme Leader Khamenei"
    summary = f"Analyst note: {secret_fact} per source."
    clean, findings = dlp.enforce(summary, classified_terms=[secret_fact])
    assert secret_fact not in clean
    assert any(x["type"] == "classified-term" for x in findings)


def test_ask_answers_pass_dlp_clean(monkeypatch):
    # a seeded canary must never survive in an outbound /v1/ask answer
    monkeypatch.setenv("ARGUS_DLP_CANARIES", "ZZNEVER-EMIT")
    reset_settings_cache()
    with TestClient(app) as c:
        b = c.post("/v1/ask", json={"text": "what is the probability of a global recession?"}).json()
        assert "ZZNEVER-EMIT" not in b["answer_markdown"]
        assert b["forecasts"]                       # still a real grounded answer
    reset_settings_cache()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
