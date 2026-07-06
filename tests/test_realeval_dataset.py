"""Real-data evaluation, Phase 1 — dataset layer.

Logic tests run on a synthetic fixture (no download needed); corpus-shape
tests run only when data/real/ is present (scripts/fetch_real_data.sh)."""
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from research.realeval.dataset import (AUTOCAST_JSON, RealQuestion, base_rate,
                                       classify_domains, load_autocast,
                                       select_mechanistic, time_split)


def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


FIXTURE = [
    {"id": 1, "status": "Resolved", "qtype": "t/f", "answer": "yes",
     "question": "Will Brent crude oil exceed $100 before 2016?", "background": "b",
     "publish_time": "2015-01-01 00:00:00+00:00", "close_time": "2015-12-31 00:00:00+00:00",
     "crowd": [{"timestamp": f"2015-0{m}-01 00:00:00+00:00", "forecast": 0.1 * m}
               for m in range(1, 7)]},
    {"id": 2, "status": "Resolved", "qtype": "t/f", "answer": "no",
     "question": "Will a ceasefire hold in the conflict through 2016?", "background": "b",
     "publish_time": "2016-01-01 00:00:00+00:00", "close_time": "2016-12-31 00:00:00+00:00",
     "crowd": [{"timestamp": f"2016-0{m}-01 00:00:00+00:00", "forecast": 0.5}
               for m in range(1, 7)]},
    {"id": 3, "status": "Resolved", "qtype": "t/f", "answer": "yes",   # off-domain
     "question": "Will a celebrity release an album?", "background": "b",
     "publish_time": "2016-01-01 00:00:00+00:00", "close_time": "2016-06-30 00:00:00+00:00",
     "crowd": [{"timestamp": "2016-01-01 00:00:00+00:00", "forecast": 0.9}] * 6},
    {"id": 4, "status": "Resolved", "qtype": "mc", "answer": "yes",    # wrong qtype
     "question": "Which oil producer cuts output?", "background": "b",
     "publish_time": "2016-01-01 00:00:00+00:00", "close_time": "2016-06-30 00:00:00+00:00",
     "crowd": [{"timestamp": "2016-01-01 00:00:00+00:00", "forecast": 0.9}] * 6},
    {"id": 5, "status": "Resolved", "qtype": "t/f", "answer": "yes",   # too few crowd pts
     "question": "Will inflation exceed 5%?", "background": "b",
     "publish_time": "2016-01-01 00:00:00+00:00", "close_time": "2016-06-30 00:00:00+00:00",
     "crowd": [{"timestamp": "2016-01-01 00:00:00+00:00", "forecast": 0.4}]},
]


def test_selection_filters_domain_qtype_and_crowd():
    qs = select_mechanistic(FIXTURE)
    assert [q.qid for q in qs] == ["1", "2"]          # sorted by close_time
    assert qs[0].domains == ["oil"] and qs[1].domains == ["conflict"]
    assert qs[0].answer is True and qs[1].answer is False


def test_crowd_at_asof_is_last_at_or_before():
    q = select_mechanistic(FIXTURE)[0]
    assert q.crowd_at(_utc(2015, 3, 15)) == pytest.approx(0.3)   # Mar 1 point
    assert q.crowd_at(_utc(2015, 1, 1)) == pytest.approx(0.1)    # exact boundary
    assert q.crowd_at(_utc(2014, 12, 31)) is None                # before any crowd
    assert q.crowd_at(_utc(2020, 1, 1)) == pytest.approx(0.6)    # after last


def test_time_split_drops_straddlers():
    qs = select_mechanistic(FIXTURE)
    calib, test = time_split(qs, _utc(2016, 1, 1))
    assert [q.qid for q in calib] == ["1"]
    assert [q.qid for q in test] == ["2"]
    # a question published 2015 but closing 2016 would appear in neither:
    straddler = RealQuestion("s", "q", "b", ["oil"], _utc(2015, 6, 1),
                             _utc(2016, 6, 1), True, [(_utc(2015, 6, 1), 0.5)])
    c2, t2 = time_split(qs + [straddler], _utc(2016, 1, 1))
    assert all(q.qid != "s" for q in c2 + t2)


def test_base_rate():
    qs = select_mechanistic(FIXTURE)
    assert base_rate(qs) == pytest.approx(0.5)


def test_domain_classifier_multilabel():
    doms = classify_domains("Will the war push Brent crude and inflation higher?")
    assert set(doms) == {"conflict", "oil", "macro"}


@pytest.mark.skipif(not os.path.exists(AUTOCAST_JSON),
                    reason="real corpus not downloaded (scripts/fetch_real_data.sh)")
def test_real_corpus_shape():
    qs = select_mechanistic(load_autocast())
    assert len(qs) >= 80                              # enough for the paper's test set
    assert all(q.publish_time < q.close_time for q in qs)
    assert all(0.0 <= p <= 1.0 for q in qs for _, p in q.crowd)
    span = (qs[-1].close_time - qs[0].close_time).days
    assert span > 365 * 3                             # multi-year walk-forward possible


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
