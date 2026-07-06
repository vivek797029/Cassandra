"""Real-data evaluation, Phase 2 — question compiler.

Real question texts from the Autocast corpus are used as fixtures verbatim
(no download needed). Predicate math is validated on a hand-built ensemble."""
import os
import sys
from datetime import date, datetime, timezone

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from research.realeval.compiler import (Compiled, Excluded, compile_question,
                                        coverage_report, extract_window)

P = datetime(2015, 9, 1, tzinfo=timezone.utc)


def test_price_threshold_below_compiles():
    c = compile_question(
        "Will the closing spot price for a barrel of Brent crude oil dip below "
        "$20.00 before 1 May 2016?", P)
    assert isinstance(c, Compiled)
    assert (c.family, c.variable, c.direction, c.threshold) == \
           ("PRICE_THRESHOLD", "oil", "below", 20.0)
    assert c.window == (P.date(), date(2016, 5, 1))


def test_macro_threshold_global_compiles_and_country_excluded():
    c = compile_question(
        "In 2016 will G7 countries experience inflation of 2% or more?", P)
    assert isinstance(c, Compiled)
    assert (c.family, c.variable, c.direction, c.threshold) == \
           ("MACRO_THRESHOLD", "inflation", "above", 2.0)
    assert c.window == (date(2016, 1, 1), date(2016, 12, 31))

    e = compile_question(
        "Will Egypt's GDP growth rate for their 2016/2017 fiscal year equal or "
        "exceed 5%?", P)
    assert isinstance(e, Excluded) and e.reason == "COUNTRY_CHANNEL"


def test_institutional_and_hazard_and_subquarter_excluded():
    e1 = compile_question(
        "Will OPEC announce any changes to its production quota before "
        "1 January 2016?", P)
    assert isinstance(e1, Excluded) and e1.reason == "INSTITUTIONAL_EVENT"

    e2 = compile_question(
        "Will Russians conduct airstrikes in Syria before 1 May 2016?", P)
    assert isinstance(e2, Excluded) and e2.reason == "HAZARD_FAMILY"

    e3 = compile_question(
        "Between 29 November 2017 and 29 December 2017, will Brent crude rise "
        "above $70?", datetime(2017, 11, 1, tzinfo=timezone.utc))
    assert isinstance(e3, Excluded) and e3.reason == "SUB_QUARTER_WINDOW"


def test_window_forms():
    assert extract_window("before 1 May 2016", P) == (P.date(), date(2016, 5, 1), "by")
    assert extract_window("by the end of 2018", P) == (P.date(), date(2018, 12, 31), "by")
    assert extract_window("by Jan 1, 2020", P) == (P.date(), date(2020, 1, 1), "by")
    w = extract_window("Between 6 June and 8 September 2018, will X happen?", P)
    assert w == (date(2018, 6, 6), date(2018, 9, 8), "between")   # explicit end day kept
    assert extract_window("will something eventually happen?", P) is None


def test_predicate_math_on_known_ensemble():
    c = Compiled("PRICE_THRESHOLD", "oil", "above", 100.0,
                 (date(2016, 1, 1), date(2016, 12, 31)), "between")
    asof = date(2016, 1, 1)
    assert c.quarters(asof) == (0, 3)          # Dec 31 lies in quarter 3, not 4
    # 4 paths x 6 quarters; exactly 2 paths cross 100 inside quarters 0-3
    sim = {"oil": np.array([
        [90, 95, 99, 98, 97, 200],     # crosses only in q5 (outside) -> no
        [90, 101, 90, 90, 90, 90],     # crosses in q1 -> yes
        [100, 90, 90, 90, 90, 90],     # touches at q0 (>=) -> yes
        [90, 90, 90, 90, 90, 90],      # never -> no
    ])}
    assert c.evaluate(sim, asof) == pytest.approx(0.5)
    below = Compiled("PRICE_THRESHOLD", "oil", "below", 91.0,
                     (date(2016, 1, 1), date(2016, 3, 1)), "by")
    assert below.quarters(asof) == (0, 0)      # Mar 1 is inside quarter 0
    assert below.evaluate(sim, asof) == pytest.approx(0.75)   # 3 of 4 start <= 91


def test_coverage_report_structure():
    class Q:
        def __init__(self, text):
            self.question, self.publish_time = text, P
    rep = coverage_report([
        Q("Will Brent crude oil rise above $60 before 1 May 2016?"),
        Q("Will OPEC announce changes before 1 January 2016?"),
        Q("Will Russians conduct airstrikes in Syria before 1 May 2016?"),
    ])
    assert rep["n"] == 3 and rep["n_compiled"] == 1
    assert rep["by_family"] == {"PRICE_THRESHOLD": 1}
    assert rep["exclusions"] == {"INSTITUTIONAL_EVENT": 1, "HAZARD_FAMILY": 1}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
