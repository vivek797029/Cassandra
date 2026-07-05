#!/usr/bin/env python3
"""Task 49 — retro question generator with ask-time snapshots + leakage check.

Generates resolvable retro questions over a historical window from data the
system actually holds (SeriesStore + raw_events), parameterized ONLY by
information available at ask time:

  series_threshold   "Will <series> <op> v0*(1+delta) within <h> days of <ask>?"
                     v0 = value_asof(ask) — captured in rule.snapshot
  event_count        "Will any <w>-day window hold >= k matching events by <ask>+<h>?"
                     k scaled from the trailing-30d count at ask time

LEAKAGE FIREWALL (blueprint §16): every rule embeds a `snapshot` block
(asof + the exact pre-ask observables used). `leakage_check()` recomputes each
snapshot using only data <= asof and fails on any mismatch, and verifies
from >= asof < by. Generators that peek at the future cannot pass it.

CLI:
  python scripts/gen_retro_questions.py --n 200 --start 2026-01-05 --end 2026-05-01
  python scripts/gen_retro_questions.py --leakage-check
"""
from __future__ import annotations
import argparse, json, os, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.question_registry.registry import QuestionRegistry
from services.question_registry.resolver import _fetch_event_ts
from services.ingest_common.series import SeriesStore
from services.ingest_common.sink import RawEventSink

D = lambda s: datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
DS = lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")

SERIES_DELTAS = [(-0.10, "<"), (0.05, ">"), (0.10, ">"), (0.20, ">")]
HORIZONS_D = [30, 60, 90]
EC_SPECS = [  # (window_days, threshold_multiplier_on_trailing30, op)
    (14, 0.5, ">="), (30, 1.0, ">="), (30, 2.0, ">="),
]


def generate(reg: QuestionRegistry, series: SeriesStore, sink: RawEventSink,
             n_target: int, start: str, end: str, step_days: int = 7,
             ec_sources: list[tuple[str, str, str]] | None = None) -> dict:
    """ec_sources: [(source, event_type, country)] for event_count families."""
    created, skipped = 0, 0
    asks = []
    t = D(start)
    while t <= D(end):
        asks.append(t)
        t += step_days * 86400
    # --- series_threshold family --------------------------------------------
    for s in series.list_series():
        for ask in asks:
            v0 = series.value_asof(s, ask)            # ask-time data ONLY
            if v0 is None:
                continue
            for delta, op in SERIES_DELTAS:
                for h in HORIZONS_D:
                    if created >= n_target:
                        break
                    key = f"retro_{s}_{DS(ask)}_{op}{int(delta*100):+d}_{h}d"
                    ok = reg.create(key, f"{s} {op} {v0*(1+delta):.2f} within {h}d of {DS(ask)}?",
                                    "economic", f"{h}d", {
                            "type": "series_threshold", "series": s, "op": op,
                            "value": round(v0 * (1 + delta), 4),
                            "from": DS(ask), "by": DS(ask + h * 86400),
                            "snapshot": {"asof": DS(ask), "value_asof": round(v0, 4)},
                        }, if_exists="ignore")
                    created += ok
                    skipped += (not ok)
    # --- event_count family ----------------------------------------------------
    for src, etype, country in (ec_sources or []):
        for ask in asks:
            rule_probe = {"source": src, "event_types": [etype], "countries": [country]}
            trailing = len(_fetch_event_ts(sink, rule_probe, ask - 30 * 86400, ask))
            for w, mult, op in EC_SPECS:
                for h in HORIZONS_D[:2]:
                    if created >= n_target:
                        break
                    k = max(1, int(round(trailing * mult)) or 1)
                    # mult tag keeps keys unique when trailing=0 collapses k to 1
                    key = (f"retro_{src}_{etype}_{country}_{DS(ask)}"
                           f"_w{w}_m{int(mult*10)}_k{k}_{h}d")
                    ok = reg.create(key, f">= {k} {etype} in {country} in any {w}d window "
                                         f"by {DS(ask + h*86400)}?",
                                    "security", f"{h}d", {
                            "type": "event_count", "source": src, "event_types": [etype],
                            "countries": [country], "window_days": w, "op": op,
                            "threshold": k, "from": DS(ask), "by": DS(ask + h * 86400),
                            "snapshot": {"asof": DS(ask), "trailing_30d": trailing},
                        }, if_exists="ignore")
                    created += ok
                    skipped += (not ok)
    return {"created": created, "skipped_existing": skipped,
            "total_retro": len([q for q in reg.list() if q["key"].startswith("retro_")])}


def leakage_check(reg: QuestionRegistry, series: SeriesStore,
                  sink: RawEventSink) -> dict:
    """Recompute every snapshot from data <= asof; any divergence = violation."""
    violations, checked = [], 0
    for q in reg.list():
        if not q["key"].startswith("retro_"):
            continue
        rule = q["resolution_rule"]
        rule = json.loads(rule) if isinstance(rule, str) else rule
        snap = rule.get("snapshot")
        if not snap:
            violations.append({"key": q["key"], "why": "missing snapshot"})
            continue
        checked += 1
        asof = D(snap["asof"])
        if not (D(rule["from"]) >= asof and D(rule["by"]) > asof):
            violations.append({"key": q["key"], "why": "window precedes asof"})
            continue
        if rule["type"] == "series_threshold":
            v = series.value_asof(rule["series"], asof)
            if v is None or round(v, 4) != snap["value_asof"]:
                violations.append({"key": q["key"], "why": "snapshot mismatch",
                                   "stored": snap["value_asof"], "recomputed": v})
        elif rule["type"] == "event_count":
            c = len(_fetch_event_ts(sink, rule, asof - 30 * 86400, asof))
            if c != snap["trailing_30d"]:
                violations.append({"key": q["key"], "why": "snapshot mismatch",
                                   "stored": snap["trailing_30d"], "recomputed": c})
    return {"checked": checked, "violations": violations,
            "passed": len(violations) == 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--start", default="2026-01-05")
    ap.add_argument("--end", default="2026-05-01")
    ap.add_argument("--leakage-check", action="store_true")
    args = ap.parse_args()
    reg, ser, snk = QuestionRegistry(), SeriesStore(), RawEventSink()
    if args.leakage_check:
        rep = leakage_check(reg, ser, snk)
        print(json.dumps(rep, indent=1))
        sys.exit(0 if rep["passed"] else 1)
    print(json.dumps(generate(reg, ser, snk, args.n, args.start, args.end,
                              ec_sources=[("acled", "battles", "Iran")]), indent=1))


if __name__ == "__main__":
    main()
