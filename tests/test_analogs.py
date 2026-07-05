"""Task 93 — learned analog metric: WL kernel, DTW, usefulness weights, and a
measured skill lift vs the Jaccard baseline (no regression)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("ARGUS_FAST", "1")

from novelty import analogs as A
from services.kg.cases import _jaccard


def test_wl_kernel_self_similarity_and_bounds():
    ch, dom = ["oil_shock", "regional_war", "strait_closure"], "energy"
    assert abs(A.wl_kernel(ch, dom, ch, dom) - 1.0) < 1e-9      # identical graphs → 1
    s = A.wl_kernel(ch, dom, ["financial_crisis", "contagion"], "macro")
    assert 0.0 <= s < 1.0
    # symmetric
    assert abs(A.wl_kernel(ch, dom, ["oil_shock"], "energy")
               - A.wl_kernel(["oil_shock"], "energy", ch, dom)) < 1e-9


def test_dtw_distance_zero_for_identical():
    t = A.trajectory(["oil_shock", "regional_war"])
    assert A.dtw_distance(t, t) == 0.0
    assert A.dtw_distance(t, A.trajectory(["de_escalation", "averted"])) > 0.0
    assert 0.0 < A.dtw_similarity(t, A.trajectory(["sanctions"])) <= 1.0


def test_usefulness_weights_favor_discriminative_channels():
    w = A.usefulness_weights()
    assert w and all(v > 0 for v in w.values())
    assert w["averted"] > 0.5                       # appears only in non-events → discriminative


def test_learned_metric_differs_from_pure_jaccard():
    cases = A.load_cases()
    c07 = next(c for c in cases if c["id"] == "c07")
    tags = ["oil_shock", "strait_closure", "regional_war"]
    learned = A.learned_similarity(tags, "energy", c07)
    assert learned > _jaccard(tags, c07["channels"])   # structure terms contribute


def test_skill_lift_measured_and_no_regression():
    r = A.skill_lift()
    assert set(r) == {"baseline", "learned", "lift"}
    assert r["lift"]["mrr"] >= 0 and r["lift"]["p5"] >= 0
    assert r["learned"]["mrr"] >= r["baseline"]["mrr"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
