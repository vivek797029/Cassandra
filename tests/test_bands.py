"""Task 83 — full-fidelity band service. Store roundtrip, the nightly worker
persists bands within budget, engines serves cached bands for the live theta,
and (regression) a poisoned/inconsistent band cache is discarded, purged, and
recomputed instead of being served.

Store isolation comes from tests/conftest.py (fresh DB per module); writes to
the live theta_hash are additionally cleaned up in-test so the module is also
safe on the shared PostgreSQL backend (DATABASE_URL CI job)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from services.copilot.store import get_store
from services.copilot.engines import Engines, BAND_KEYS
from workers.bands import refresh as bands_refresh


def test_store_band_cache_roundtrip():
    s = get_store()
    bands = {"ME_war_1y": {"lo": 0.40, "hi": 0.55, "conformal_q80": 0.6},
             "Brent_gt120_1y": {"lo": 0.30, "hi": 0.50, "conformal_q80": 0.55}}
    try:
        s.bands_save("deadbeefcafe", bands, n_paths=3000, fidelity="full")
        got = s.bands_get("deadbeefcafe")
        assert got and got["fidelity"] == "full" and got["n_paths"] == 3000
        assert got["bands"]["ME_war_1y"]["lo"] == 0.40
        assert s.bands_get("no-such-theta") is None
    finally:
        assert s.bands_delete("deadbeefcafe") == 2      # cleanup verifies rowcount
    assert s.bands_get("deadbeefcafe") is None


def test_worker_refresh_persists_within_budget():
    Engines(fast=True)                                   # ensure a promoted theta exists (fast load)
    rep = bands_refresh.refresh(fast=True, budget_seconds=7200)
    assert rep["within_budget"] and rep["n_keys"] == len(BAND_KEYS)
    assert rep["fidelity"] == "fast"
    cached = get_store().bands_get(rep["theta_hash"])
    assert cached and set(cached["bands"]) >= set(BAND_KEYS)
    get_store().bands_delete(rep["theta_hash"])          # leave shared backends clean


def test_budget_overrun_is_flagged():
    rep = bands_refresh.refresh(fast=True, budget_seconds=0.0)   # impossible budget
    assert rep["within_budget"] is False                  # SLO guard trips
    get_store().bands_delete(rep.get("theta_hash", ""))


def test_engines_prefers_cached_bands():
    e1 = Engines(fast=True)
    th = e1.theta_hash
    # Distinctive but CONSISTENT markers: each band brackets the live baseline
    # probability, so the serving consistency guard accepts the cache.
    marker = {k: {"center": e1.events[k],
                  "lo": max(0.0, round(e1.events[k] - 0.101, 6)),
                  "hi": min(1.0, round(e1.events[k] + 0.101, 6)),
                  "conformal_q80": 0.333}
              for k in BAND_KEYS}
    try:
        get_store().bands_save(th, marker, n_paths=3000, fidelity="full")
        e2 = Engines(fast=True)                           # same theta → same hash → cache hit
        assert e2.theta_hash == th
        assert e2.bands_source.startswith("cache")
        assert e2.bands["ME_war_1y"]["conformal_q80"] == 0.333
        assert e2.forecast("ME_war_1y")["band"]["conformal_q80"] == 0.333  # API shape
        b = e2.forecast("ME_war_1y")["band"]
        assert b["lo"] <= e2.events["ME_war_1y"] <= b["hi"]  # served bands stay consistent
    finally:
        get_store().bands_delete(th)


def test_engines_discards_inconsistent_cached_bands():
    """Regression: a band cache that contradicts the live baseline probability
    (e.g. leaked test markers, stale writer, polluted store) must NOT be served.
    Engines drops it, purges the rows, and recomputes."""
    e1 = Engines(fast=True)
    th = e1.theta_hash
    poison = {k: {"center": 0.15, "lo": 0.111, "hi": 0.222, "conformal_q80": 0.333}
              for k in BAND_KEYS}
    assert any(not (0.111 <= e1.events[k] <= 0.222) for k in BAND_KEYS
               if e1.events.get(k) is not None)           # poison really is inconsistent
    try:
        get_store().bands_save(th, poison, n_paths=3000, fidelity="full")
        e2 = Engines(fast=True)
        assert e2.theta_hash == th
        assert e2.bands_source.startswith("computed")     # cache rejected
        for k in BAND_KEYS:                               # served output honors the contract
            p, b = e2.events.get(k), e2.bands.get(k)
            if p is not None and b:
                assert b["lo"] <= p <= b["hi"]
        assert get_store().bands_get(th) is None          # poison purged (self-heal)
    finally:
        get_store().bands_delete(th)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
