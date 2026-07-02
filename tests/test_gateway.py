"""Task 74 — gateway authz tests: clearance model, JWT verification, and the
FastAPI dependencies under both enabled and disabled auth."""
import os, sys
from types import SimpleNamespace
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/gateway_test.db")

import pytest
from fastapi.testclient import TestClient

from services.gateway import auth, clearance
from services.gateway.clearance import Principal, principal_from_claims, normalize_clearance
from services.copilot.config import reset_settings_cache
from services.copilot.main import app

SECRET = "test-secret"


def _stub(secret=SECRET, aud=None, iss=None, algs=("HS256",), jwks=None):
    return SimpleNamespace(jwt_secret=secret, jwt_audience=aud, jwt_issuer=iss,
                           jwt_algorithm_list=list(algs), jwks_url=jwks)


# ------------------------------------------------------------- clearance ----
def test_clearance_total_order_and_access():
    assert clearance.level_of("OPEN") < clearance.level_of("CONFIDENTIAL") \
        < clearance.level_of("SECRET") < clearance.level_of("TOPSECRET")
    assert Principal("u", "SECRET").can_access("CONFIDENTIAL")
    assert not Principal("u", "OPEN").can_access("SECRET")
    assert Principal("u", "SECRET").can_access("SECRET")        # equal passes


def test_clearance_normalization_fails_closed():
    assert normalize_clearance("ts") == "TOPSECRET"
    assert normalize_clearance("Confidential") == "CONFIDENTIAL"
    assert normalize_clearance("nonsense") == "OPEN"           # unknown → least privilege
    assert normalize_clearance(None) == "OPEN"


def test_principal_from_claims_maps_scopes_and_persona():
    p = principal_from_claims({"sub": "a1", "clearance": "SECRET",
                               "scope": "read write", "persona": "principal"})
    assert p.sub == "a1" and p.clearance == "SECRET" and p.persona == "principal"
    assert p.scopes == ["read", "write"]
    # a forged/garbage clearance claim cannot widen access
    assert principal_from_claims({"sub": "x", "clearance": "GODMODE"}).clearance == "OPEN"


# ------------------------------------------------------------- JWT verify ---
def test_mint_verify_roundtrip():
    tok = auth.mint_token("u1", "SECRET", secret=SECRET, scopes=["read"])
    claims = auth.verify_token(tok, _stub())
    assert claims["sub"] == "u1" and claims["clearance"] == "SECRET"


def test_expired_token_rejected():
    tok = auth.mint_token("u1", "OPEN", secret=SECRET, ttl=-10)
    with pytest.raises(auth.AuthError) as e:
        auth.verify_token(tok, _stub())
    assert "expired" in e.value.reason


def test_bad_signature_rejected():
    tok = auth.mint_token("u1", "OPEN", secret=SECRET)
    with pytest.raises(auth.AuthError):
        auth.verify_token(tok, _stub(secret="WRONG-KEY"))


def test_audience_and_issuer_enforced():
    tok = auth.mint_token("u1", "OPEN", secret=SECRET, audience="argus", issuer="idp")
    assert auth.verify_token(tok, _stub(aud="argus", iss="idp"))["sub"] == "u1"
    with pytest.raises(auth.AuthError) as e:
        auth.verify_token(tok, _stub(aud="other", iss="idp"))
    assert "audience" in e.value.reason
    with pytest.raises(auth.AuthError) as e2:
        auth.verify_token(tok, _stub(aud="argus", iss="evil"))
    assert "issuer" in e2.value.reason


def test_missing_token_rejected():
    with pytest.raises(auth.AuthError):
        auth.verify_token("", _stub())


# --------------------------------------------------- FastAPI deps (enabled) --
@pytest.fixture
def authed(monkeypatch):
    monkeypatch.setenv("ARGUS_AUTH_ENABLED", "1")
    monkeypatch.setenv("ARGUS_JWT_SECRET", SECRET)
    monkeypatch.setenv("ARGUS_JWT_ISSUER", "https://idp.test")
    monkeypatch.setenv("ARGUS_JWT_AUDIENCE", "argus")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _tok(clear, **kw):
    return auth.mint_token("analyst-7", clear, secret=SECRET,
                           issuer="https://idp.test", audience="argus", **kw)


def test_whoami_requires_token_when_enabled(authed):
    c = TestClient(app)
    assert c.get("/v1/whoami").status_code == 401
    r = c.get("/v1/whoami", headers={"Authorization": f"Bearer {_tok('CONFIDENTIAL')}"})
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "analyst-7" and body["clearance"] == "CONFIDENTIAL"


def test_clearance_gate_enforced(authed):
    c = TestClient(app)
    assert c.get("/v1/admin/ping",
                 headers={"Authorization": f"Bearer {_tok('OPEN')}"}).status_code == 403
    assert c.get("/v1/admin/ping",
                 headers={"Authorization": f"Bearer {_tok('SECRET')}"}).status_code == 200


def test_expired_and_bad_audience_yield_401(authed):
    c = TestClient(app)
    expired = _tok("SECRET", ttl=-5)
    assert c.get("/v1/whoami", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    wrong_aud = auth.mint_token("u", "SECRET", secret=SECRET,
                                issuer="https://idp.test", audience="someone-else")
    assert c.get("/v1/whoami", headers={"Authorization": f"Bearer {wrong_aud}"}).status_code == 401


# --------------------------------------------------- FastAPI deps (disabled) -
def test_disabled_auth_returns_trusted_local_principal(monkeypatch):
    monkeypatch.delenv("ARGUS_AUTH_ENABLED", raising=False)
    reset_settings_cache()
    c = TestClient(app)
    r = c.get("/v1/whoami")                         # no token needed in dev
    assert r.status_code == 200 and r.json()["sub"] == "dev-local"
    assert c.get("/v1/admin/ping").status_code == 200   # dev clearance (SECRET) passes
    reset_settings_cache()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
