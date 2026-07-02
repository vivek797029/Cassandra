"""Task 83 — full-fidelity band service. Store roundtrip, the nightly worker
persists bands within budget, and engines serves cached bands for the live theta."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")
os.environ.setdefault("ARGUS_DB", "/tmp/argus/bands_test.db")

from services.copilot.store import get_store
from services.copilot.engines import Engines, BAND_KEYS
from workers.bands import refresh as bands_refresh


def test_store_band_cache_roundtrip():
    s = get_store()
    bands = {"ME_war_1y": {"lo": 0.40, "hi": 0.55, "conformal_q80": 0.6},
             "Brent_gt120_1y": {"lo": 0.30, "hi": 0.50, "conformal_q80": 0.55}}
    s.bands_save("deadbeefcafe", bands, n_paths=3000, fidelity="full")
    got = s.bands_get("deadbeefcafe")
    assert got and got["fidelity"] == "full" and got["n_paths"] == 3000
    assert got["bands"]["ME_war_1y"]["lo"] == 0.40
    assert s.bands_get("no-such-theta") is None


def test_worker_refresh_persists_within_budget():
    Engines(fast=True)                                   # ensure a promoted theta exists (fast load)
    rep = bands_refresh.refresh(fast=True, budget_seconds=7200)
    assert rep["within_budget"] and rep["n_keys"] == len(BAND_KEYS)
    assert rep["fidelity"] == "fast"
    cached = get_store().bands_get(rep["theta_hash"])
    assert cached and set(cached["bands"]) >= set(BAND_KEYS)


def test_budget_overrun_is_flagged():
    rep = bands_refresh.refresh(fast=True, budget_seconds=0.0)   # impossible budget
    assert rep["within_budget"] is False                  # SLO guard trips


def test_engines_prefers_cached_bands():
    e1 = Engines(fast=True)
    th = e1.theta_hash
    marker = {k: {"center": 0.15, "lo": 0.111, "hi": 0.222, "conformal_q80": 0.333}
              for k in BAND_KEYS}
    get_store().bands_save(th, marker, n_paths=3000, fidelity="full")
    e2 = Engines(fast=True)                               # same theta → same hash → cache hit
    assert e2.theta_hash == th
    assert e2.bands_source.startswith("cache")
    assert e2.bands["ME_war_1y"]["lo"] == 0.111
    assert e2.forecast("ME_war_1y")["band"]["lo"] == 0.111   # served through the API shape


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
