"""Task 82 — engine sharding. Three region slices run in parallel and merge into an
ensemble whose event probabilities match a single-process run within Monte-Carlo
noise; the engine honors ARGUS_ENGINE_SHARDS."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/shard_test.db")

import pytest
from core.engine import THETA_DEFAULT, WorldEngine, event_probs
from services.copilot.sharding import sharded_simulate, merge_sims, shard_sizes, DEFAULT_REGIONS
from services.copilot.config import reset_settings_cache

HEADLINE = ["ME_war_1y", "Hormuz_closure_by_end2027", "Brent_gt120_1y"]


def test_shard_sizes_partition_exactly():
    assert shard_sizes(2000, 3) == [666, 666, 668]
    assert sum(shard_sizes(3000, 4)) == 3000


def test_three_regions_run_in_parallel_and_merge_equivalently():
    base = event_probs(WorldEngine(theta=THETA_DEFAULT, seed=42).simulate(N=3000, Q=12, seed=42))
    res = sharded_simulate(THETA_DEFAULT, N=3000, Q=12, seed=42, shards=3,
                           region_names=DEFAULT_REGIONS)
    # merged ensemble is the union of the three slices
    assert res["sim"]["N"] == 3000
    assert [s["region"] for s in res["shards"]] == sorted(DEFAULT_REGIONS)
    assert sum(s["paths"] for s in res["shards"]) == 3000
    # the slices actually ran concurrently, and faster than serial
    assert res["parallel"] is True
    assert res["wall_s"] <= res["serial_s"]
    # merged probabilities match the single-process run within MC noise
    for k in HEADLINE:
        assert abs(res["events"][k] - base[k]) < 0.08, (k, res["events"][k], base[k])


def test_merge_preserves_path_dimension():
    sims = [WorldEngine(theta=THETA_DEFAULT, seed=s).simulate(N=500, Q=8, seed=s)
            for s in (1, 2, 3)]
    merged = merge_sims(sims)
    assert merged["N"] == 1500
    assert merged["oil"].shape == (1500, 8) and merged["me"].shape == (1500, 8)


def test_engine_honors_shard_setting(monkeypatch):
    monkeypatch.setenv("ARGUS_ENGINE_SHARDS", "3")
    reset_settings_cache()
    from services.copilot.engines import Engines
    e = Engines(fast=True)
    assert e.shard_report and len(e.shard_report) == 3
    assert e.base_sim["N"] == 4000
    reset_settings_cache()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
