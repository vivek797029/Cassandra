"""Task 85 — counterfactual cache: stable clause hash, LRU eviction, and a repeat
counterfactual served from cache in well under 10ms."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/cfcache_test.db")

from services.copilot.cfcache import clause_key, get_cf_cache, reset_cf_cache, _LRU
from services.copilot.engines import Engines


def test_clause_key_stable_and_sensitive():
    a = clause_key(["x"], {"me_esc": 0.8}, ["ME_war_1y"], 12, 2000, "th1")
    b = clause_key(["x"], {"me_esc": 0.8}, ["ME_war_1y"], 12, 2000, "th1")
    c = clause_key(["x"], {"me_esc": 0.9}, ["ME_war_1y"], 12, 2000, "th1")
    assert a == b and a != c


def test_lru_evicts_oldest():
    lru = _LRU(2)
    lru.set("a", 1); lru.set("b", 2); lru.set("c", 3)
    assert lru.get("a") is None and lru.get("b") == 2 and lru.get("c") == 3


def test_repeat_counterfactual_is_cached_fast_and_equal():
    reset_cf_cache()
    e = Engines(fast=True)
    args = (["Gulf maritime verification coalition"], {}, ["ME_war_1y", "Brent_gt120_1y"], 12, 1500)
    r1 = e.counterfactual(*args)
    t0 = time.time(); r2 = e.counterfactual(*args); cached_s = time.time() - t0
    assert r1 == r2
    assert cached_s < 0.01, f"cached cf took {cached_s*1000:.1f}ms (>10ms)"
    assert get_cf_cache().stats()["hits"] >= 1
    # a different clause is a miss → distinct result
    r3 = e.counterfactual(["EM bridge-financing window"], {}, ["ME_war_1y"], 12, 1500)
    assert r3["manifest_id"] != r1["manifest_id"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
