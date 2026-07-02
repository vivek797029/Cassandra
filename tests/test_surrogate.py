"""Task 84 — surrogate spike (B6). The MLP surrogate over (state,theta,do) reaches
>=100x speedup vs the full Monte-Carlo sim with held-out error < 2pp."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")

import numpy as np
from research.surrogate.surrogate import (build, simulate_probs, HEADLINE,
                                          DO_HANDLES, _perturbed_theta)


def test_ground_truth_shape_range_and_determinism():
    x = np.array([1, 1, 1, 1, 1, 1, 1.0])
    y1 = simulate_probs(x, N=800)
    y2 = simulate_probs(x, N=800)
    assert y1.shape == (len(HEADLINE),)
    assert ((y1 >= 0) & (y1 <= 1)).all()
    assert np.allclose(y1, y2)                       # fixed CRN seed → deterministic surface
    assert len(DO_HANDLES) == 6


def test_theta_perturbation_changes_theta():
    assert not np.allclose(_perturbed_theta(0.9), _perturbed_theta(1.1))


def test_surrogate_speedup_and_accuracy():
    r = build(n_train=300, n_test=80, N=1000, epochs=3000)
    assert r["mae"] < 0.02, f"held-out MAE {r['mae']*100:.2f}pp exceeds 2pp"
    assert r["max_err"] < 0.05, r["max_err"]
    assert r["speedup"] >= 100, f"speedup {r['speedup']:.0f}x below 100x"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
