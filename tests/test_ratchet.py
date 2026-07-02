"""Task 94 — frozen-baseline rack + ratchet regression gate. A candidate that scores
worse than the best frozen ancestor is blocked; the rack is re-scored each run."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")

from core.engine import THETA_DEFAULT
from novelty.cassandra import CalibrationTrainer, transfer_theta
from workers.ratchet import rack as R


def _trained():
    return transfer_theta(CalibrationTrainer(n_paths=800).train(iters=12, verbose=False))


def test_frozen_brier_is_deterministic():
    b1 = R.frozen_brier(THETA_DEFAULT, n_paths=800)
    b2 = R.frozen_brier(THETA_DEFAULT, n_paths=800)
    assert b1 == b2 and 0.0 <= b1 <= 1.0


def test_ratchet_blocks_a_regression(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_BASELINE_RACK", str(tmp_path / "rack.json"))
    good = _trained()
    b_good = R.frozen_brier(good, 800)
    b_def = R.frozen_brier(THETA_DEFAULT, 800)
    R.freeze_baseline("champion", good, n_paths=800)
    # candidate equal to the frozen champion → no regression
    assert R.regression_gate(good, n_paths=800)["pass"] is True
    # the untrained default scores worse → ratchet blocks it
    assert b_def > b_good + R.TOL
    res = R.regression_gate(THETA_DEFAULT, n_paths=800)
    assert res["pass"] is False and res["delta"] > 0
    assert res["best_ancestor"] == "champion"


def test_empty_rack_passes(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_BASELINE_RACK", str(tmp_path / "empty.json"))
    assert R.regression_gate(THETA_DEFAULT, n_paths=600)["pass"] is True


def test_rescore_reports_every_baseline(tmp_path, monkeypatch):
    monkeypatch.setenv("ARGUS_BASELINE_RACK", str(tmp_path / "r.json"))
    R.freeze_baseline("v1", THETA_DEFAULT, n_paths=600)
    R.freeze_baseline("v1", THETA_DEFAULT, n_paths=600)      # idempotent (same hash)
    rs = R.rescore(600)
    assert len(rs) == 1 and "brier_now" in rs[0]


def test_committed_rack_has_a_baseline():
    rack = R.load_rack(os.path.join(os.path.dirname(__file__), "..", "data", "baseline_rack.json"))
    assert rack and all("theta_hash" in e and "theta" in e for e in rack)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
