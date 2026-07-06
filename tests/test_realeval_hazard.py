"""Real-data evaluation, Phase 2b — hazard-clock family."""
import math
import os
import sys
from datetime import date, datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from research.realeval.compiler import Excluded
from research.realeval.hazard import (CompiledHazard, HazardModel,
                                      compile_hazard,
                                      fit_lambda, training_samples)

P = datetime(2015, 9, 1, tzinfo=timezone.utc)


def test_real_texts_classify_and_compile():
    c = compile_hazard("Will Russians conduct airstrikes in Syria before 1 May 2016?", P)
    assert isinstance(c, CompiledHazard) and c.event_class == "AIRSTRIKE"
    assert c.window == (P.date(), date(2016, 5, 1))

    c2 = compile_hazard("Before 18 October 2016, will there be a confrontation involving "
                        "Iran's and another country's national military forces?", P)
    assert isinstance(c2, CompiledHazard) and c2.event_class == "CONFRONTATION"

    c3 = compile_hazard("Will a US-led military action occur in N. Korea by the end of 2018?", P)
    assert isinstance(c3, CompiledHazard) and c3.event_class == "MILITARY_ACTION"

    e = compile_hazard("Will casualties from the Turkey-PKK conflict exceed 125 in any "
                       "month from August through November 2017?", P)
    assert isinstance(e, Excluded) and e.reason == "COUNT_THRESHOLD"


def test_mle_recovers_known_rate():
    # With outcome probability exactly 1-exp(-l*d), the MLE recovers l:
    lam_true, d = 1.5, 0.8
    y = 1.0 - math.exp(-lam_true * d)
    lam_hat = fit_lambda([(d, y)] * 50)
    assert lam_hat == pytest.approx(lam_true, rel=1e-3)


def test_mle_boundary_behavior():
    assert fit_lambda([(1.0, 0.0)] * 10) == pytest.approx(0.01)      # never occurs -> floor
    assert fit_lambda([(1.0, 1.0)] * 10) == pytest.approx(20.0)      # always occurs -> cap
    assert fit_lambda([]) == pytest.approx(0.01)                     # no data -> floor


def test_pooling_shrinks_sparse_classes():
    # 40 balanced global observations, one sparse all-yes class:
    samples = [("CONFRONTATION", 1.0, i % 2 == 0) for i in range(40)]
    samples += [("AIRSTRIKE", 1.0, True)] * 2
    m = HazardModel(alpha=2.0).fit(samples)
    unsmoothed = fit_lambda([(1.0, 1.0)] * 2)
    assert m.rates["AIRSTRIKE"] < unsmoothed          # pulled off the cap
    assert m.rates["AIRSTRIKE"] > m.rates["CONFRONTATION"]  # data still speaks


def test_predict_asof_clipping_and_bands():
    m = HazardModel().fit([("AIRSTRIKE", 1.0, i % 2 == 0) for i in range(20)])
    cq = CompiledHazard("AIRSTRIKE", (date(2016, 1, 1), date(2016, 12, 31)), "by")
    early = m.predict(cq, date(2016, 1, 1))
    late = m.predict(cq, date(2016, 10, 1))
    assert 0 < late["probability"] < early["probability"] < 1     # less exposure left
    assert m.predict(cq, date(2017, 6, 1))["probability"] == 0.0  # window passed
    b = early["band"]
    assert b["lo"] < early["probability"] < b["hi"]               # ball brackets center


def test_training_samples_leakage_guard():
    class Q:
        def __init__(self, text, pub, close, ans):
            self.question, self.publish_time, self.close_time, self.answer = \
                text, pub, close, ans
    qs = [
        Q("Will Russians conduct airstrikes in Syria before 1 May 2016?",
          P, datetime(2016, 5, 1, tzinfo=timezone.utc), True),
        Q("Will a ceasefire hold before 1 May 2017?",                       # closes later
          P, datetime(2017, 5, 1, tzinfo=timezone.utc), False),
    ]
    cut = datetime(2016, 6, 1, tzinfo=timezone.utc)
    s = training_samples(qs, cut)
    assert len(s) == 1 and s[0][0] == "AIRSTRIKE" and s[0][2] is True


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
