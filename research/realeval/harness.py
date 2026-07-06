"""Real-data evaluation — walk-forward harness + metrics (paper Phase 3).

Protocol
--------
For every hazard-compilable question and every as-of date on a fixed grid of
lifetime fractions, the model is refitted from scratch on questions RESOLVED
strictly before that as-of date (no same-question or future information can
enter), then scored against the resolution:

    forecast record = (qid, asof, p_model, band, p_crowd, p_base, y)

Baselines at the same as-of date:
    crowd      last crowd probability at or before asof (skip pair if none)
    base rate  YES-rate of all mechanistic questions resolved before asof
    uniform    0.5

Metrics: mean Brier per system (paired over identical (q, asof) pairs),
reliability table (10 bins), and an uncertainty-usefulness check — the rank
correlation between band width and squared error (wide bands should mark the
forecasts that miss).

Ablations rerun the identical protocol with one component removed:
    no_pooling   alpha=0 (classes fit alone; sparse classes hit the clamps)
    no_classes   single global rate for every event class
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import timedelta

from research.realeval.dataset import RealQuestion
from research.realeval.hazard import (CompiledHazard, HazardModel,
                                      compile_hazard, training_samples)

ASOF_FRACTIONS = (0.1, 0.3, 0.5, 0.7, 0.9)
MIN_TRAIN = 5                                  # refuse to forecast on thinner history


@dataclass
class Record:
    qid: str
    event_class: str
    asof: str
    p_model: float
    band_lo: float
    band_hi: float
    p_crowd: float
    p_base: float
    y: int
    n_train: int


def _base_rate_before(qs: list[RealQuestion], before) -> float | None:
    done = [q for q in qs if q.close_time < before]
    if len(done) < MIN_TRAIN:
        return None
    return sum(q.answer for q in done) / len(done)


def hazard_questions(qs: list[RealQuestion]) -> list[tuple[RealQuestion, CompiledHazard]]:
    out = []
    for q in qs:
        c = compile_hazard(q.question, q.publish_time)
        if isinstance(c, CompiledHazard):
            out.append((q, c))
    return out


def run_walkforward(qs: list[RealQuestion], alpha: float = 2.0, rho: float = 0.10,
                    classes: bool = True,
                    fractions: tuple[float, ...] = ASOF_FRACTIONS) -> list[Record]:
    """Full leakage-guarded panel. `classes=False` collapses every event class
    to one global clock (ablation)."""
    records: list[Record] = []
    for q, cq in hazard_questions(qs):
        life = q.close_time - q.publish_time
        for f in fractions:
            asof_dt = q.publish_time + timedelta(seconds=f * life.total_seconds())
            crowd = q.crowd_at(asof_dt)
            base = _base_rate_before(qs, asof_dt)
            train = training_samples(qs, asof_dt)
            if crowd is None or base is None or len(train) < MIN_TRAIN:
                continue
            if not classes:
                train = [("ALL", d, y) for _, d, y in train]
                cq_eff = CompiledHazard("ALL", cq.window, cq.kind)
            else:
                cq_eff = cq
            m = HazardModel(alpha=alpha, rho=rho).fit(train)
            pred = m.predict(cq_eff, asof_dt.date())
            records.append(Record(
                qid=q.qid, event_class=cq.event_class, asof=asof_dt.date().isoformat(),
                p_model=round(pred["probability"], 6),
                band_lo=round(pred["band"]["lo"], 6),
                band_hi=round(pred["band"]["hi"], 6),
                p_crowd=round(float(crowd), 6), p_base=round(base, 6),
                y=int(q.answer), n_train=len(train)))
    return records


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------
def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def summarize(records: list[Record]) -> dict:
    n = len(records)
    if n == 0:
        return {"n": 0}
    mb = {name: sum(brier(getattr(r, f), r.y) for r in records) / n
          for name, f in (("model", "p_model"), ("crowd", "p_crowd"),
                          ("base_rate", "p_base"))}
    mb["uniform"] = sum(brier(0.5, r.y) for r in records) / n
    bins: list[list[int]] = [[0, 0] for _ in range(10)]     # [count, yes]
    for r in records:
        b = min(9, int(r.p_model * 10))
        bins[b][0] += 1
        bins[b][1] += r.y
    reliability = [{"bin": f"{i/10:.1f}-{(i+1)/10:.1f}", "n": c,
                    "mean_outcome": round(s / c, 4) if c else None}
                   for i, (c, s) in enumerate(bins)]
    widths = [r.band_hi - r.band_lo for r in records]
    errs = [brier(r.p_model, r.y) for r in records]
    return {"n": n, "n_questions": len({r.qid for r in records}),
            "mean_brier": {k: round(v, 4) for k, v in mb.items()},
            "skill_vs_crowd": round(1.0 - mb["model"] / mb["crowd"], 4) if mb["crowd"] else None,
            "reliability": reliability,
            "band_width_mean": round(sum(widths) / n, 4),
            "band_error_rank_corr": round(_spearman(widths, errs), 4)}


def _rank(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):                       # average ranks over ties
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(a: list[float], b: list[float]) -> float:
    if len(a) < 3:
        return 0.0
    ra, rb = _rank(a), _rank(b)
    ma, mb_ = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb_) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb_) ** 2 for y in rb))
    return num / (da * db) if da and db else 0.0


def bootstrap_brier_diff(records: list[Record], n_boot: int = 10000,
                         seed: int = 42) -> dict:
    """Cluster bootstrap (resampling QUESTIONS, not records — records within a
    question share its outcome) of the crowd-minus-model Brier difference.
    Positive difference = model better. Returns mean and the 2.5/97.5 pct CI."""
    import random
    rng = random.Random(seed)
    by_q: dict[str, list[Record]] = {}
    for r in records:
        by_q.setdefault(r.qid, []).append(r)
    qids = sorted(by_q)
    diffs = []
    for _ in range(n_boot):
        sample = [by_q[rng.choice(qids)] for _ in qids]
        rs = [r for grp in sample for r in grp]
        d = sum(brier(r.p_crowd, r.y) - brier(r.p_model, r.y) for r in rs) / len(rs)
        diffs.append(d)
    diffs.sort()
    return {"mean": round(sum(diffs) / n_boot, 5),
            "ci95": [round(diffs[int(0.025 * n_boot)], 5),
                     round(diffs[int(0.975 * n_boot)], 5)],
            "p_model_better": round(sum(d > 0 for d in diffs) / n_boot, 4)}


def by_lifetime_fraction(records: list[Record], qs: list[RealQuestion]) -> list[dict]:
    """Model-vs-crowd Brier at each as-of grid point: the crowd is weakest
    early (near its 0.5 seed) and strongest late — report the whole curve."""
    from datetime import date as _date
    life = {q.qid: (q.publish_time, q.close_time) for q in qs}
    buckets: dict[float, list[Record]] = {}
    for r in records:
        pub, close = life[r.qid]
        f = ((_date.fromisoformat(r.asof) - pub.date()).days /
             max((close - pub).days, 1))
        key = min(ASOF_FRACTIONS, key=lambda g: abs(g - f))
        buckets.setdefault(key, []).append(r)
    out = []
    for f in sorted(buckets):
        rs = buckets[f]
        out.append({"fraction": f, "n": len(rs),
                    "brier_model": round(sum(brier(r.p_model, r.y) for r in rs) / len(rs), 4),
                    "brier_crowd": round(sum(brier(r.p_crowd, r.y) for r in rs) / len(rs), 4)})
    return out


def full_evaluation(qs: list[RealQuestion]) -> dict:
    """Primary run + ablations + inference, one JSON blob (the paper's data)."""
    primary = run_walkforward(qs)
    out = {"primary": summarize(primary),
           "bootstrap_crowd_minus_model": bootstrap_brier_diff(primary),
           "by_lifetime_fraction": by_lifetime_fraction(primary, qs),
           "records": [asdict(r) for r in primary],
           "ablations": {
               "no_pooling": summarize(run_walkforward(qs, alpha=0.0)),
               "no_classes": summarize(run_walkforward(qs, classes=False))}}
    return json.loads(json.dumps(out))          # ensure plain-JSON types
