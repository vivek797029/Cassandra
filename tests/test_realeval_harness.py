"""Real-data evaluation, Phase 3 — walk-forward harness + metrics.
Synthetic corpus with a KNOWN generating hazard rate: the harness must beat a
mis-set crowd, honor the leakage guard, and produce sane metric structure."""
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from research.realeval.dataset import RealQuestion
from research.realeval.harness import (Record, brier, full_evaluation,
                                       run_walkforward, summarize, _spearman)

T0 = datetime(2016, 1, 1, tzinfo=timezone.utc)


def _mk_corpus(n=60, lam=0.7, crowd_p=0.5, seed=7) -> list[RealQuestion]:
    """Questions of one class with true hazard `lam`/yr, 1y windows, spread
    over 6 years so early questions resolve before late ones are forecast."""
    rng = random.Random(seed)
    qs = []
    for i in range(n):
        pub = T0 + timedelta(days=30 * i)
        close = pub + timedelta(days=365)
        p_true = 1.0 - math.exp(-lam * 1.0)
        y = rng.random() < p_true
        crowd = [(pub + timedelta(days=d), crowd_p) for d in (0, 90, 180, 270)]
        qs.append(RealQuestion(
            qid=str(i), question=f"Will an armed conflict occur in region {i} "
            f"before {close.strftime('%d %B %Y')}?", background="",
            domains=["conflict"], publish_time=pub, close_time=close,
            answer=y, crowd=crowd))
    return qs


def test_records_are_leakage_guarded_and_clipped():
    qs = _mk_corpus()
    recs = run_walkforward(qs)
    assert len(recs) > 50
    by_asof_qid = {(r.qid, r.asof) for r in recs}
    assert len(by_asof_qid) == len(recs)              # no duplicate pairs
    for r in recs:
        q = qs[int(r.qid)]
        assert q.publish_time.date().isoformat() <= r.asof < q.close_time.date().isoformat()
        assert 0.0 <= r.p_model <= 1.0
        assert r.band_lo <= r.p_model <= r.band_hi
        assert r.n_train >= 5                          # MIN_TRAIN enforced


def test_model_learns_true_rate_and_beats_missset_crowd():
    # true p(1y) ~ 0.503; crowd stuck at 0.9 -> model must win on Brier
    qs = _mk_corpus(lam=0.7, crowd_p=0.9)
    s = summarize(run_walkforward(qs))
    assert s["n"] > 50
    assert s["mean_brier"]["model"] < s["mean_brier"]["crowd"]
    assert s["skill_vs_crowd"] > 0


def test_late_asof_probabilities_shrink():
    qs = _mk_corpus()
    recs = run_walkforward(qs)
    per_q = {}
    for r in recs:
        per_q.setdefault(r.qid, []).append((r.asof, r.p_model))
    monotone_down = 0
    total = 0
    for ps in per_q.values():
        ps.sort()
        if len(ps) >= 2:
            total += 1
            monotone_down += ps[-1][1] < ps[0][1]      # less exposure left
    assert total > 0 and monotone_down == total


def test_summarize_structure_and_spearman():
    r = [Record("1", "C", "2020-01-01", 0.2, 0.1, 0.3, 0.5, 0.4, 0, 10),
         Record("2", "C", "2020-01-01", 0.9, 0.8, 1.0, 0.5, 0.4, 1, 10),
         Record("3", "C", "2020-01-01", 0.1, 0.0, 0.2, 0.5, 0.4, 0, 10)]
    s = summarize(r)
    assert s["n"] == 3 and s["n_questions"] == 3
    assert s["mean_brier"]["uniform"] == pytest.approx(0.25)
    assert sum(b["n"] for b in s["reliability"]) == 3
    assert brier(0.2, 0) == pytest.approx(0.04)
    assert _spearman([1, 2, 3, 4], [2, 4, 6, 8]) == pytest.approx(1.0)
    assert _spearman([1, 2, 3, 4], [8, 6, 4, 2]) == pytest.approx(-1.0)


def test_full_evaluation_shape():
    res = full_evaluation(_mk_corpus(n=40))
    assert set(res) == {"primary", "records", "ablations",
                        "bootstrap_crowd_minus_model", "by_lifetime_fraction"}
    assert res["bootstrap_crowd_minus_model"]["ci95"][0] <= \
           res["bootstrap_crowd_minus_model"]["mean"] <= \
           res["bootstrap_crowd_minus_model"]["ci95"][1]
    assert all(row["n"] > 0 for row in res["by_lifetime_fraction"])
    assert set(res["ablations"]) == {"no_pooling", "no_classes"}
    assert res["primary"]["n"] == len(res["records"]) > 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
