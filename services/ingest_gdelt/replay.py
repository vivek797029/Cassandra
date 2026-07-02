"""Task 43 — GDELT replay quality gate.

Replays a SEQUENCE of export batches (the live feed re-publishes and
overlaps; backfills replay months of 15-min files) and verifies ingestion
quality with hard gates:

  GATE 1  db_dup_groups == 0          post-ingest (source,source_id) uniqueness, NULL-id audited
  GATE 2  bad_row_rate  < 5%          malformed/bad-date rows across the replay
  GATE 3  geo_coverage  >= 60%        share of rows with a geo cell (GDELT norm ~70-90%)

Report also includes: incoming duplicate rate (feed overlap absorbed by the
sink — informational, NOT gated: overlap is expected), per-batch stats,
event-type distribution, freshness lag.

CLI:
  python -m services.ingest_gdelt.replay batch1.zip batch2.zip ...   # exit 1 on gate failure
"""
from __future__ import annotations
import argparse, json, os, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.ingest_common.sink import RawEventSink
from services.ingest_gdelt import worker

GATES = {"max_bad_row_rate": 0.05, "min_geo_coverage": 0.60}


def replay(batches: list, sink: RawEventSink) -> dict:
    per_batch, totals = [], {"received": 0, "inserted": 0, "duplicates": 0,
                             "rows_bad": 0, "rows_no_geo": 0}
    type_counts: dict[str, int] = {}
    max_occurred = 0.0
    for b in batches:
        events, q = worker.parse_export(worker.read_batch(b))
        res = sink.insert_many(events)
        for e in events:
            type_counts[e["event_type"]] = type_counts.get(e["event_type"], 0) + 1
            max_occurred = max(max_occurred, e["occurred_at"])
        stat = {"batch": str(b)[-40:], **res, **q}
        per_batch.append(stat)
        for k in totals:
            totals[k] += stat.get(k, 0)

    rows_seen = totals["received"] + totals["rows_bad"]
    report = {
        "batches": len(batches),
        "totals": totals,
        "incoming_dup_rate": round(totals["duplicates"] / max(totals["received"], 1), 4),
        "bad_row_rate": round(totals["rows_bad"] / max(rows_seen, 1), 4),
        "db_rows": sink.count("gdelt"),
        "db_dup_groups": sink.dup_groups("gdelt"),
        "db_null_id_rows": sink.null_id_rows("gdelt"),
        "geo_coverage": round(sink.geo_coverage("gdelt"), 4),
        "freshness_lag_h": round((time.time() - max_occurred) / 3600, 1) if max_occurred else None,
        "event_type_dist": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])[:8]),
        "per_batch": per_batch,
    }
    report["gates"] = {
        "dedup_integrity": report["db_dup_groups"] == 0,
        "bad_row_rate": report["bad_row_rate"] < GATES["max_bad_row_rate"],
        "geo_coverage": report["geo_coverage"] >= GATES["min_geo_coverage"],
    }
    report["passed"] = all(report["gates"].values())
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("batches", nargs="+", help="export .zip/.csv files, oldest first")
    args = ap.parse_args()
    rep = replay(args.batches, RawEventSink())
    print(json.dumps(rep, indent=1))
    sys.exit(0 if rep["passed"] else 1)


if __name__ == "__main__":
    main()
