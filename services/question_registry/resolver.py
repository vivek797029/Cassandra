"""ARGUS — question resolver v1 (Task 48).

Auto-resolves pending registry questions against observed data. This closes
the loop that feeds calibration training with REAL outcomes (blueprint §25).

Rule types:
  series_threshold  {"series","op","value","by"[,"from"]}
      YES at first ts in [from, by] where `value <op> threshold` (SeriesStore);
      NO once `by` has passed without a crossing.
  event_count       {"source","event_types"[],"countries"[]?,"window_days",
                     "op","threshold","by"[,"from"]}
      YES if ANY rolling window of window_days within [from, by] contains
      <op> threshold matching events in raw_events (sliding two-pointer);
      NO once `by` passes without one. Countries match actors.country.
  manual            never auto-resolves (API /resolve only).

Semantics: evidence is recorded in the report; resolution writes through the
registry (resolved flag + outcome + timestamp). Already-resolved questions are
skipped — re-runs are no-ops.

CLI:  python -m services.question_registry.resolver --once
API:  POST /v1/questions/resolver/run
"""
from __future__ import annotations
import argparse, json, os, sys, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.question_registry.registry import QuestionRegistry
from services.ingest_common.sink import RawEventSink
from services.ingest_common.series import SeriesStore

OPS = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "<": lambda a, b: a < b, "<=": lambda a, b: a <= b}

def _ts(date_str: str | None, default: float) -> float:
    if not date_str:
        return default
    return datetime.strptime(date_str, "%Y-%m-%d").replace(
        tzinfo=timezone.utc).timestamp()

# ------------------------------------------------------------- event_count --
def _fetch_event_ts(sink: RawEventSink, rule: dict, t0: float, t1: float) -> list[float]:
    src = rule.get("source")
    types = set(rule.get("event_types") or [])
    countries = set(rule.get("countries") or [])
    q = ("SELECT event_type, actors, occurred_at FROM raw_events "
         "WHERE source = {p} AND occurred_at >= {p} AND occurred_at <= {p}")
    if sink.backend == "postgres":
        qpg = ("SELECT event_type, actors, "
               "EXTRACT(EPOCH FROM occurred_at)::float8 AS occurred_at FROM raw_events "
               "WHERE source = %s AND occurred_at >= to_timestamp(%s) "
               "AND occurred_at <= to_timestamp(%s)")
        with sink.conn.cursor() as cur:
            cur.execute(qpg, (src, t0, t1))
            rows = [(r["event_type"], r["actors"], r["occurred_at"])
                    for r in cur.fetchall()]
    else:
        rows = sink.conn.execute(q.format(p="?"), (src, t0, t1)).fetchall()
    out = []
    for etype, actors, occ in rows:
        if types and etype not in types:
            continue
        if countries:
            a = actors if isinstance(actors, dict) else json.loads(actors or "{}")
            if a.get("country") not in countries:
                continue
        out.append(float(occ))
    return sorted(out)

def _max_rolling_count(ts_sorted: list[float], window_s: float) -> tuple[int, float | None]:
    """Max #events in any rolling window; returns (count, window_end_ts)."""
    best, best_end, i = 0, None, 0
    for j in range(len(ts_sorted)):
        while ts_sorted[j] - ts_sorted[i] > window_s:
            i += 1
        if j - i + 1 > best:
            best, best_end = j - i + 1, ts_sorted[j]
    return best, best_end

# ----------------------------------------------------------------- resolve --
def check_rule(rule: dict, sink: RawEventSink, series: SeriesStore,
               now: float) -> tuple[int | None, dict]:
    """Returns (outcome|None-if-pending, evidence)."""
    rtype = rule.get("type", "manual")
    if rtype == "manual":
        return None, {"reason": "manual rule"}
    by = _ts(rule.get("by"), now + 1)
    frm = _ts(rule.get("from"), 0.0)

    if rtype == "series_threshold":
        cross = series.first_crossing(rule["series"], rule["op"], rule["value"],
                                      frm, min(by, now))
        if cross is not None:
            return 1, {"crossing_ts": cross, "series": rule["series"]}
        if now > by:
            return 0, {"reason": "deadline passed without crossing"}
        return None, {"reason": "no crossing yet; deadline ahead"}

    if rtype == "event_count":
        window_s = float(rule.get("window_days", 28)) * 86400
        ts = _fetch_event_ts(sink, rule, frm, min(by, now))
        count, wend = _max_rolling_count(ts, window_s)
        hit = OPS[rule.get("op", ">=")](count, float(rule["threshold"]))
        if hit:
            return 1, {"max_window_count": count, "window_end_ts": wend,
                       "events_considered": len(ts)}
        if now > by:
            return 0, {"reason": "deadline passed", "max_window_count": count,
                       "events_considered": len(ts)}
        return None, {"reason": "threshold not reached yet",
                      "max_window_count": count, "events_considered": len(ts)}

    return None, {"reason": f"unknown rule type '{rtype}'"}

def resolve_pending(reg: QuestionRegistry, sink: RawEventSink | None = None,
                    series: SeriesStore | None = None, now: float | None = None) -> dict:
    sink = sink or RawEventSink()
    series = series or SeriesStore()
    now = now or time.time()
    report = {"checked": 0, "resolved_yes": 0, "resolved_no": 0, "pending": 0,
              "manual_or_unknown": 0, "details": []}
    for q in reg.list(resolved=False):
        rule = q.get("resolution_rule")
        rule = json.loads(rule) if isinstance(rule, str) else (rule or {})
        report["checked"] += 1
        outcome, evidence = check_rule(rule, sink, series, now)
        d = {"key": q["key"], "rule_type": rule.get("type", "manual"),
             "evidence": evidence}
        if outcome is None:
            kind = "manual_or_unknown" if rule.get("type", "manual") == "manual" \
                   or "unknown rule" in evidence.get("reason", "") else "pending"
            report[kind] += 1
            d["status"] = kind
        else:
            reg.resolve(q["key"], outcome)
            report["resolved_yes" if outcome else "resolved_no"] += 1
            d["status"] = f"resolved:{outcome}"
        report["details"].append(d)
    return report

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true")
    ap.parse_args()
    rep = resolve_pending(QuestionRegistry())
    print(json.dumps(rep, indent=1, default=str))

if __name__ == "__main__":
    main()
