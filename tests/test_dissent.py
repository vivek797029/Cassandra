"""Task 87 — dissent / right-of-reply. A signed dissent is filed by the verified
principal and then travels with the forecast render for every future reader."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/dissent_test.db")

import pytest
from fastapi.testclient import TestClient
from services.gateway import auth
from services.copilot.config import reset_settings_cache
from services.copilot.store import get_store
from services.copilot.main import app

SECRET = "test-secret"


@pytest.fixture
def authed(monkeypatch):
    monkeypatch.setenv("ARGUS_AUTH_ENABLED", "1")
    monkeypatch.setenv("ARGUS_JWT_SECRET", SECRET)
    reset_settings_cache()
    yield
    reset_settings_cache()


def _bearer(clear="SECRET"):
    return {"Authorization": f"Bearer {auth.mint_token('analyst', clear, secret=SECRET)}"}


def test_store_dissent_roundtrip():
    did = get_store().dissent_save("K1", "alice", "SECRET", "concern", "sig123")
    rows = get_store().dissents_for("K1")
    assert any(r["id"] == did and r["author"] == "alice" and r["signature"] == "sig123"
               for r in rows)


def test_dissent_signed_and_travels_with_render(authed):
    c = TestClient(app)
    r = c.post("/v1/dissents",
               json={"key": "ME_war_1y", "text": "overstated given the ceasefire track"},
               headers=_bearer("SECRET"))
    assert r.status_code == 200
    d = r.json()
    assert d["author"] == "analyst" and len(d["signature"]) == 32

    # travels with the forecast render
    f = c.get("/v1/forecasts/ME_war_1y").json()
    assert any(x["id"] == d["id"] and "overstated" in x["text"] for x in f["dissents"])

    # and is listed
    lst = c.get("/v1/dissents", params={"key": "ME_war_1y"}).json()
    assert any(x["id"] == d["id"] for x in lst)


def test_dissent_requires_authentication(authed):
    c = TestClient(app)
    assert c.post("/v1/dissents", json={"key": "X", "text": "y"}).status_code == 401


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
