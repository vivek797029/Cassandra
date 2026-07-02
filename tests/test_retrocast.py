"""Task 96 — RETRO-CAST v1: 5k stratified, leakage-clean, deterministically frozen."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "backfill_retro", os.path.join(os.path.dirname(__file__), "..", "scripts", "backfill_retro.py"))
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)


def test_generates_5000_stratified_leakage_clean():
    qs = bf.generate(5000)
    assert len(qs) == 5000
    assert len({q["id"] for q in qs}) == 5000                 # unique ids
    sc = bf.strata_counts(qs)
    assert len(sc) == len(bf.DOMAINS) * len(bf.HORIZONS) * len(bf.FAMILIES)  # every cell
    assert min(sc.values()) >= 100                            # stratified coverage
    assert bf.leakage_check(qs) == []                         # no future leakage


def test_generation_is_deterministic():
    assert bf.content_hash(bf.generate(2000)) == bf.content_hash(bf.generate(2000))


def test_frozen_manifest_matches_and_verifies():
    m = bf.freeze(5000)                                        # write manifest
    assert m["n"] == 5000 and m["version"] == "v1"
    assert m["sha256"] == bf.content_hash(bf.generate(5000))
    assert bf.verify() is True                                 # re-generate → hash matches


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
