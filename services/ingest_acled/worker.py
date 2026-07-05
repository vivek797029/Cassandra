"""ARGUS ingestion — ACLED worker (Task 44).

ACLED = curated political-violence/protest events (weekly releases, ~1990s+).
API: https://api.acleddata.com/acled/read?key=...&email=...  (JSON pages)
Credentials via config: ACLED_KEY / ACLED_EMAIL (workers refuse live mode without them).

Modes:
  python -m services.ingest_acled.worker --file events.json|.csv   # offline batch (tests, drops)
  python -m services.ingest_acled.worker --once [--days 14]        # latest window via API
  python -m services.ingest_acled.worker --backfill 24             # N months, paged

Record fields used: event_id_cnty (stable id) · event_date YYYY-MM-DD ·
event_type / sub_event_type · actor1 / actor2 · country / admin1 ·
latitude / longitude · geo_precision (1 best..3) · time_precision ·
fatalities · source · notes.

Normalization (ingestion contract, same as GDELT worker):
  event_type  = slugged ACLED type (battles, protests, riots, explosions_remote_violence,
                violence_against_civilians, strategic_developments)
  magnitude   = fatalities (count; NOT comparable to GDELT Goldstein — consumers
                must branch on `source`, see payload.magnitude_kind)
  confidence  = precision-based: geo/time precision 1->0.9, 2->0.6, 3->0.35 (min of both)
  h3_cell     = shared cell_for() from the GDELT worker (H3 res-5 / grid fallback)
Dedup: (source='acled', source_id=event_id_cnty).
"""
from __future__ import annotations
import argparse, csv, json, os, sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.ingest_common.sink import RawEventSink
from services.ingest_gdelt.worker import cell_for
from services.copilot.config import get_settings

API_URL = "https://api.acleddata.com/acled/read"
PRECISION_CONF = {1: 0.9, 2: 0.6, 3: 0.35}

TYPE_SLUG = {
    "battles": "battles",
    "protests": "protests",
    "riots": "riots",
    "explosions/remote violence": "explosions_remote_violence",
    "violence against civilians": "violence_against_civilians",
    "strategic developments": "strategic_developments",
}

def _conf(rec: dict) -> float:
    g = int(rec.get("geo_precision") or 2)
    t = int(rec.get("time_precision") or 2)
    return min(PRECISION_CONF.get(g, 0.5), PRECISION_CONF.get(t, 0.5))

def _fl(v) -> float | None:
    try:
        s = str(v).strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None

def parse_records(records: list[dict]) -> tuple[list[dict], dict]:
    events, bad, no_geo = [], 0, 0
    for r in records:
        rid = (r.get("event_id_cnty") or "").strip()
        date = (r.get("event_date") or "").strip()
        if not rid or not date:
            bad += 1
            continue
        try:
            occurred = datetime.strptime(date, "%Y-%m-%d").replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            bad += 1
            continue
        lat, lon = _fl(r.get("latitude")), _fl(r.get("longitude"))
        if lat is None or lon is None:
            no_geo += 1
        etype = TYPE_SLUG.get((r.get("event_type") or "").strip().lower(),
                              "other_" + (r.get("event_type") or "unknown")
                              .strip().lower().replace(" ", "_")[:40])
        events.append({
            "source": "acled",
            "source_id": rid,
            "event_type": etype,
            "actors": {"a1": (r.get("actor1") or "").strip() or None,
                       "a2": (r.get("actor2") or "").strip() or None,
                       "country": (r.get("country") or "").strip() or None},
            "h3_cell": cell_for(lat, lon),
            "occurred_at": occurred,
            "magnitude": _fl(r.get("fatalities")) or 0.0,
            "confidence": _conf(r),
            "payload": {"sub_event_type": (r.get("sub_event_type") or "").strip(),
                        "admin1": (r.get("admin1") or "").strip(),
                        "magnitude_kind": "fatalities",
                        "geo_precision": r.get("geo_precision"),
                        "time_precision": r.get("time_precision"),
                        "acled_source": (r.get("source") or "").strip()[:200],
                        "lat": lat, "lon": lon,
                        "notes": (r.get("notes") or "").strip()[:300]},
        })
    return events, {"rows_parsed": len(events), "rows_bad": bad, "rows_no_geo": no_geo}

def read_batch(path: str) -> list[dict]:
    """Accept ACLED JSON ({'data': [...]} or bare list) or CSV with header."""
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        return doc["data"] if isinstance(doc, dict) else doc
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def fetch_api(days: int, page: int = 1, limit: int = 5000) -> list[dict]:
    import httpx
    s = get_settings()
    if not (s.acled_key and s.acled_email):
        raise RuntimeError("live mode needs ACLED_KEY and ACLED_EMAIL (see .env.example)")
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    out: list[dict] = []
    while True:
        r = httpx.get(API_URL, params={
            "key": s.acled_key, "email": s.acled_email,
            "event_date": since, "event_date_where": ">=",
            "limit": limit, "page": page}, timeout=120)
        r.raise_for_status()
        data = r.json().get("data", [])
        out.extend(data)
        if len(data) < limit:
            return out
        page += 1

def ingest(records: list[dict], sink: RawEventSink, bus=None) -> dict:
    events, quality = parse_records(records)
    res = {}
    if bus is not None:
        from services.ingest_common.bus import TOPIC_RAW_ACLED
        res["published"] = bus.publish(TOPIC_RAW_ACLED, events, producer="ingest_acled")
    res.update(sink.insert_many(events))
    res.update(quality)
    res["acled_total"] = sink.count("acled")
    res["db_dup_groups"] = sink.dup_groups("acled")
    return res

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", help="local .json/.csv drop (offline batch)")
    ap.add_argument("--once", action="store_true", help="fetch latest window via API")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--backfill", type=int, metavar="MONTHS",
                    help="page through N months of history")
    ap.add_argument("--publish", action="store_true",
                    help="also publish to the event bus (ingest.raw.acled)")
    args = ap.parse_args()
    sink = RawEventSink()
    bus = None
    if args.publish:
        from services.ingest_common.bus import get_bus
        bus = get_bus()
    if args.file:
        print(json.dumps(ingest(read_batch(args.file), sink, bus), indent=1))
    elif args.backfill:
        print(json.dumps(ingest(fetch_api(days=args.backfill * 30), sink, bus), indent=1))
    elif args.once:
        print(json.dumps(ingest(fetch_api(days=args.days), sink, bus), indent=1))
    else:
        ap.print_help()

if __name__ == "__main__":
    main()
