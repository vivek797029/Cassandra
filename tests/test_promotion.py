"""Task 89 — theta promotion workflow: dual-control sign-off + tamper-evident audit
chain. An unsigned / under-approved promotion is rejected; two distinct non-requester
approvers are required."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/promo_test.db")

import pytest
from core.engine import THETA_DEFAULT, THETA_NAMES
from services.copilot.store import get_store
from services.admin.promote import ThetaPromotionWorkflow, PromotionError
from services.gateway import auth
from services.copilot.config import reset_settings_cache
from fastapi.testclient import TestClient
from services.copilot.main import app

SECRET = "test-secret"


def _save_theta(h):
    get_store().theta_save(h, list(THETA_NAMES), [float(x) for x in THETA_DEFAULT], 0.2, "test")


def test_unsigned_promotion_rejected():
    wf = ThetaPromotionWorkflow(get_store())
    _save_theta("hashUNS")
    wf.request("hashUNS", "alice")
    with pytest.raises(PromotionError):           # no approvals at all
        wf.promote("hashUNS")


def test_requester_cannot_self_approve_and_needs_two_distinct():
    wf = ThetaPromotionWorkflow(get_store())
    _save_theta("hashDC")
    wf.request("hashDC", "alice", "new champion")
    with pytest.raises(PromotionError):
        wf.approve("hashDC", "alice")             # self-approval blocked
    wf.approve("hashDC", "bob")
    wf.approve("hashDC", "bob")                    # duplicate doesn't double-count
    with pytest.raises(PromotionError):
        wf.promote("hashDC")                       # only 1 distinct approver
    st = wf.approve("hashDC", "carol")
    assert st["ready"] and st["approvals"] == 2
    out = wf.promote("hashDC")
    assert out["promoted"] is True
    assert get_store().theta_promoted()["theta_hash"] == "hashDC"


def test_audit_chain_is_tamper_evident():
    wf = ThetaPromotionWorkflow(get_store())
    _save_theta("hashAUD")
    wf.request("hashAUD", "alice")
    wf.approve("hashAUD", "bob")
    wf.approve("hashAUD", "carol")
    wf.promote("hashAUD")
    assert wf.verify_chain() is True
    assert [e["action"] for e in wf.chain][:1] == ["theta.promotion.request"]
    wf.chain[1]["detail"] = "tampered"            # mutate a link
    assert wf.verify_chain() is False


@pytest.fixture
def authed(monkeypatch):
    monkeypatch.setenv("ARGUS_AUTH_ENABLED", "1")
    monkeypatch.setenv("ARGUS_JWT_SECRET", SECRET)
    reset_settings_cache()
    yield
    reset_settings_cache()


def _tok(sub, clear="SECRET"):
    return {"Authorization": f"Bearer {auth.mint_token(sub, clear, secret=SECRET)}"}


def test_admin_api_enforces_clearance_and_dual_control(authed):
    _save_theta("hashAPI")
    c = TestClient(app)
    assert c.post("/v1/admin/theta/request", json={"theta_hash": "hashAPI"},
                  headers=_tok("alice", "OPEN")).status_code == 403       # under-cleared
    assert c.post("/v1/admin/theta/request", json={"theta_hash": "hashAPI"},
                  headers=_tok("alice")).status_code == 200
    assert c.post("/v1/admin/theta/promote", json={"theta_hash": "hashAPI"},
                  headers=_tok("alice")).status_code == 409               # unsigned rejected
    c.post("/v1/admin/theta/approve", json={"theta_hash": "hashAPI"}, headers=_tok("bob"))
    c.post("/v1/admin/theta/approve", json={"theta_hash": "hashAPI"}, headers=_tok("carol"))
    assert c.post("/v1/admin/theta/promote", json={"theta_hash": "hashAPI"},
                  headers=_tok("dave")).json()["promoted"] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
