"""Task 75 — cell-level clearance redaction. A SECRET fact is hidden from an OPEN
principal; a CONFIDENTIAL fact is hidden from OPEN but shown to CONFIDENTIAL+; a
SECRET cell on an otherwise-visible fact is masked. Driven by data/classification.json
(F1=SECRET, F4=CONFIDENTIAL, F2.source=SECRET)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/redaction_test.db")

import pytest
from fastapi.testclient import TestClient

from services.gateway.clearance import Principal
from services.gateway import classification, auth
from services.copilot.config import reset_settings_cache
from services.copilot.main import app

SAMPLE = [
    {"id": "F1", "domain": "security", "text": "secret fact", "source": "s1"},
    {"id": "F2", "domain": "security", "text": "open fact", "source": "classified-src"},
    {"id": "F4", "domain": "security", "text": "confidential fact", "source": "s4"},
    {"id": "F9", "domain": "economy", "text": "open econ fact", "source": "s9"},
]


@pytest.fixture(autouse=True)
def _fresh():
    classification.reset_classification_cache()
    yield
    classification.reset_classification_cache()


# --------------------------------------------------------------- unit -------
def test_open_hides_secret_and_confidential_and_masks_cell():
    r = classification.redact_facts(SAMPLE, Principal("u", "OPEN"))
    ids = {f["id"] for f in r["facts"]}
    assert "F1" not in ids and "F4" not in ids        # SECRET + CONFIDENTIAL withheld
    assert ids == {"F2", "F9"}
    f2 = next(f for f in r["facts"] if f["id"] == "F2")
    assert "REDACTED" in f2["source"] and f2["text"] == "open fact"   # cell masked, text kept
    assert r["hidden"] == 2 and r["cells_masked"] == 1


def test_secret_sees_everything_unmasked():
    r = classification.redact_facts(SAMPLE, Principal("u", "SECRET"))
    assert {f["id"] for f in r["facts"]} == {"F1", "F2", "F4", "F9"}
    f2 = next(f for f in r["facts"] if f["id"] == "F2")
    assert f2["source"] == "classified-src"
    assert r["hidden"] == 0 and r["cells_masked"] == 0


def test_confidential_sees_f4_not_f1_cell_still_masked():
    r = classification.redact_facts(SAMPLE, Principal("u", "CONFIDENTIAL"))
    ids = {f["id"] for f in r["facts"]}
    assert "F4" in ids and "F1" not in ids
    f2 = next(f for f in r["facts"] if f["id"] == "F2")
    assert "REDACTED" in f2["source"]                 # SECRET cell masked at CONFIDENTIAL


def test_notice_is_clearance_honest():
    assert classification.redaction_notice(
        classification.redact_facts(SAMPLE, Principal("u", "SECRET"))) is None
    note = classification.redaction_notice(
        classification.redact_facts(SAMPLE, Principal("u", "OPEN")))
    assert note and "withheld" in note


# ----------------------------------------------------- API (auth enabled) ---
@pytest.fixture
def authed(monkeypatch):
    monkeypatch.setenv("ARGUS_AUTH_ENABLED", "1")
    monkeypatch.setenv("ARGUS_JWT_SECRET", "test-secret")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _tok(clear):
    return auth.mint_token("analyst", clear, secret="test-secret")


def test_v1_facts_redacted_for_open_visible_for_secret(authed):
    c = TestClient(app)
    open_r = c.get("/v1/facts", headers={"Authorization": f"Bearer {_tok('OPEN')}"})
    assert open_r.status_code == 200
    open_ids = {f["id"] for f in open_r.json()}
    assert "F1" not in open_ids and "F4" not in open_ids          # real F1 SECRET hidden
    assert open_r.headers["X-Argus-Redacted"] == "2"
    f2 = next(f for f in open_r.json() if f["id"] == "F2")
    assert "REDACTED" in f2["source"]                            # cell masked

    sec_r = c.get("/v1/facts", headers={"Authorization": f"Bearer {_tok('SECRET')}"})
    sec_ids = {f["id"] for f in sec_r.json()}
    assert "F1" in sec_ids and "F4" in sec_ids
    assert sec_r.headers["X-Argus-Redacted"] == "0"


def test_status_answer_redacts_secret_fact_for_open(authed):
    c = TestClient(app)
    open_b = c.post("/v1/ask", json={"text": "give me a situation overview"},
                    headers={"Authorization": f"Bearer {_tok('OPEN')}"}).json()
    assert "Khamenei" not in open_b["answer_markdown"]            # F1 (SECRET) withheld
    assert "🔒" in open_b["answer_markdown"]                       # redaction notice shown

    sec_b = c.post("/v1/ask", json={"text": "give me a situation overview"},
                   headers={"Authorization": f"Bearer {_tok('SECRET')}"}).json()
    assert "🔒" not in sec_b["answer_markdown"]                    # nothing withheld at SECRET


def test_disabled_auth_dev_principal_sees_all():
    # default dev principal clearance = SECRET → nothing redacted (back-compat)
    c = TestClient(app)
    r = c.get("/v1/facts")
    assert r.headers["X-Argus-Redacted"] == "0"
    assert {f["id"] for f in r.json()} >= {"F1", "F4"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
