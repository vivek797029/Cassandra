"""Task 98 — cost/query target met under the tuned config; over-provisioning fails;
caching lowers cost."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from services.ops import cost_model as CM

PERF = os.path.join(os.path.dirname(__file__), "..", "docs", "perf", "performance-and-cost.md")


def test_tuned_config_meets_cost_target():
    r = CM.report()
    assert r["meets"] is True and 0 < r["cost_per_query"] <= r["target"]


def test_over_provisioning_breaks_target():
    assert CM.report(replicas=20, cpu=4, mem=8)["meets"] is False


def test_cache_lowers_cost_and_throughput_amortizes():
    hi = CM.cost_per_query(CM.PILOT_QPS, cache_hit_rate=0.0)
    lo = CM.cost_per_query(CM.PILOT_QPS, cache_hit_rate=0.9)
    assert lo <= hi                                     # cache cuts LLM calls
    assert CM.cost_per_query(1.0) < CM.cost_per_query(0.05)   # throughput amortizes infra


def test_perf_doc_present_with_rightsizing_and_ttls():
    t = open(PERF, encoding="utf-8").read().lower()
    assert "right-sizing" in t and "cache ttls" in t and "cost" in t and "freeze" in t


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
