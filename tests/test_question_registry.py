"""Task 47 — question registry: store CRUD + API router + engine seed."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_DB", "/tmp/argus/test_registry_host.db")

import pytest
from services.copilot.config import reset_settings_cache
from services.question_registry.registry import QuestionRegistry, seed_from_engines


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "c.db"))
    reset_settings_cache()
    r = QuestionRegistry(sqlite_path=str(tmp_path / "registry.db"))
    yield r
    r.close()
    reset_settings_cache()


def test_crud_roundtrip(reg):
    assert reg.create("Q_test_1", "Will X happen?", "security", "12m",
                      {"type": "manual"}) is True
    q = reg.get("Q_test_1")
    assert q["text"] == "Will X happen?" and q["resolved"] is False
    with pytest.raises(KeyError):
        reg.create("Q_test_1", "dup", "security")
    assert reg.create("Q_test_1", "dup", "security", if_exists="ignore") is False


def test_resolve_and_filters(reg):
    reg.create("Q_a", "A?", "economic")
    reg.create("Q_b", "B?", "security")
    out = reg.resolve("Q_a", 1)
    assert out["resolved"] is True and out["outcome"] == 1 and out["resolved_at"]
    assert {q["key"] for q in reg.list(resolved=True)} == {"Q_a"}
    assert {q["key"] for q in reg.list(resolved=False)} == {"Q_b"}
    assert {q["key"] for q in reg.list(domain="security")} == {"Q_b"}
    with pytest.raises(KeyError):
        reg.resolve("Q_missing", 0)


def test_seed_from_engines_idempotent(reg):
    n1 = seed_from_engines(reg)
    n2 = seed_from_engines(reg)
    assert n1 >= 16 and n2 == 0
    me = reg.get("ME_war_1y")
    assert me["domain"] == "security"
    brent = reg.get("Brent_gt120_1y")
    assert '"series_threshold"' in brent["resolution_rule"]
    dem = reg.get("Dem_House_Nov2026")
    assert dem["domain"] == "political"


def test_api_router(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ARGUS_DB", str(tmp_path / "api.db"))
    reset_settings_cache()
    from services.question_registry import api as qapi
    qapi.reset_registry()
    from fastapi.testclient import TestClient
    from services.copilot.main import app
    with TestClient(app) as c:
        qs = c.get("/v1/questions").json()
        assert len(qs) >= 16                                    # seeded at startup
        assert isinstance(qs[0]["resolution_rule"], dict)       # JSON decoded
        r = c.post("/v1/questions", json={"key": "Q_api_1", "text": "API test?",
                                          "domain": "social"})
        assert r.status_code == 201
        assert c.post("/v1/questions", json={"key": "Q_api_1", "text": "dup",
                                             "domain": "social"}).status_code == 409
        assert c.get("/v1/questions/Q_api_1").json()["domain"] == "social"
        assert c.get("/v1/questions/NOPE").status_code == 404
        res = c.post("/v1/questions/Q_api_1/resolve", json={"outcome": 1})
        assert res.json()["resolved"] is True and res.json()["outcome"] == 1
        assert c.post("/v1/questions/Q_api_1/resolve",
                      json={"outcome": 5}).status_code == 422
        resolved = c.get("/v1/questions", params={"resolved": True}).json()
        assert "Q_api_1" in {q["key"] for q in resolved}
    qapi.reset_registry()
    reset_settings_cache()
