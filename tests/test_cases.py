"""Task 92 — case library: 50 valid causal cartridges (incl. non-events) and an
analog-retrieval metric eval that passes its thresholds."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from services.kg import cases as C


def test_library_has_50_valid_cartridges_with_nonevents():
    cs = C.load_cases()
    assert len(cs) >= 50
    ids = [c["id"] for c in cs]
    assert len(set(ids)) == len(ids)                         # unique ids
    for c in cs:
        assert C.REQUIRED <= set(c), f"{c.get('id')} missing fields"
        assert c["channels"] and isinstance(c["channels"], list)
    # survivorship guard: a meaningful fraction are crises that did NOT escalate
    assert sum(1 for c in cs if c["is_nonevent"]) >= 8


def test_mechanism_overlap_retrieval_ranks_relevant():
    top = [cid for cid, _ in C.retrieve(["oil_shock", "strait_closure", "regional_war"], k=3)]
    assert "c07" in top                                      # the all-channels match ranks in top-3
    assert all(s > 0 for _, s in C.retrieve(["nuclear_crisis", "great_power"], k=3))


def test_analog_eval_meets_thresholds():
    r = C.eval_analogs()
    assert r["n_cases"] >= 50
    assert r["nonevent_fraction"] >= 0.15
    assert r["precision_at_3"] >= 0.6
    assert r["mrr"] >= 0.6
    assert r["mechanism_floor_ok"] is True


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
