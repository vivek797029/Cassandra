"""ARGUS ingestion — GDELT 2.0 Events worker (Task 42).

Modes:
  python -m services.ingest_gdelt.worker --file path/to/export.zip|.csv   # offline batch (tests, backfill)
  python -m services.ingest_gdelt.worker --once                            # fetch latest 15-min batch
  python -m services.ingest_gdelt.worker --loop                            # poll every 15 min

GDELT v2 export format: 61 tab-separated columns, no header.
Columns used (0-indexed): 0 GlobalEventID · 1 Day(YYYYMMDD) · 6 Actor1Name ·
16 Actor2Name · 26 EventCode · 28 EventRootCode · 29 QuadClass ·
30 GoldsteinScale · 32 NumSources · 34 AvgTone · 56 ActionGeo_Lat ·
57 ActionGeo_Long · 53 ActionGeo_CountryCode · 60 SOURCEURL

Normalization:
  event_type   = CAMEO root code -> readable label (CAMEO_ROOT)
  magnitude    = GoldsteinScale (-10 cooperative .. +10 conflictual inverted scale)
  confidence   = min(1, NumSources/10)  — multi-source corroboration proxy
  h3_cell      = H3 res-5 cell when `h3` lib present; else 0.5-degree grid id
  occurred_at  = Day at 00:00 UTC (GDELT event-day granularity)
Dedup: (source='gdelt', source_id=GlobalEventID) unique in raw_events.
"""
from __future__ import annotations
import argparse, csv, io, os, sys, time, zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.ingest_common.sink import RawEventSink

LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
N_COLS = 61

CAMEO_ROOT = {
    "01": "public_statement", "02": "appeal", "03": "express_intent_cooperate",
    "04": "consult", "05": "diplomatic_cooperation", "06": "material_cooperation",
    "07": "provide_aid", "08": "yield", "09": "investigate", "10": "demand",
    "11": "disapprove", "12": "reject", "13": "threaten", "14": "protest",
    "15": "exhibit_force_posture", "16": "reduce_relations", "17": "coerce",
    "18": "assault", "19": "fight", "20": "unconventional_mass_violence",
}

def cell_for(lat: float | None, lon: float | None) -> str | None:
    if lat is None or lon is None:
        return None
    try:
        import h3                                    # optional dependency
        return h3.latlng_to_cell(lat, lon, 5)
    except Exception:
        return f"g5:{round(lat * 2) / 2:.1f},{round(lon * 2) / 2:.1f}"   # 0.5-deg grid fallback

def _f(row: list[str], i: int) -> float | None:
    try:
        v = row[i].strip()
        return float(v) if v else None
    except (IndexError, ValueError):
        return None

def parse_export(fileobj: io.TextIOBase) -> tuple[list[dict], dict]:
    """Parse a GDELT v2 export CSV stream -> (normalized events, quality stats)."""
    events, bad_rows, no_geo = [], 0, 0
    reader = csv.reader(fileobj, delimiter="\t")
    for row in reader:
        if len(row) < N_COLS:
            bad_rows += 1
            continue
        try:
            day = row[1].strip()
            occurred = datetime.strptime(day, "%Y%m%d").replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            bad_rows += 1
            continue
        lat, lon = _f(row, 56), _f(row, 57)
        if lat is None or lon is None:
            no_geo += 1
        nsources = _f(row, 32) or 1.0
        root = row[28].strip().zfill(2) if row[28].strip() else ""
        events.append({
            "source": "gdelt",
            "source_id": row[0].strip(),
            "event_type": CAMEO_ROOT.get(root, f"cameo_{root or 'unknown'}"),
            "actors": {"a1": row[6].strip() or None, "a2": row[16].strip() or None,
                       "country": row[53].strip() or None},
            "h3_cell": cell_for(lat, lon),
            "occurred_at": occurred,
            "magnitude": _f(row, 30),                       # Goldstein scale
            "confidence": min(1.0, nsources / 10.0),
            "payload": {"event_code": row[26].strip(), "quad_class": row[29].strip(),
                        "avg_tone": _f(row, 34), "num_sources": int(nsources),
                        "lat": lat, "lon": lon, "url": row[60].strip()[:500]},
        })
    return events, {"rows_parsed": len(events), "rows_bad": bad_rows, "rows_no_geo": no_geo}

def read_batch(path_or_bytes) -> io.TextIOBase:
    """Accept a .zip (GDELT delivery format), plain .csv path/bytes, or a
    text file-like object (passed through unchanged)."""
    if hasattr(path_or_bytes, "read") and not isinstance(path_or_bytes, (bytes, bytearray)):
        return path_or_bytes
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
        if data[:2] == b"PK":
            zf = zipfile.ZipFile(io.BytesIO(data))
            return io.TextIOWrapper(zf.open(zf.namelist()[0]), encoding="utf-8",
                                    errors="replace")
        return io.StringIO(data.decode("utf-8", "replace"))
    if str(path_or_bytes).endswith(".zip"):
        zf = zipfile.ZipFile(path_or_bytes)
        return io.TextIOWrapper(zf.open(zf.namelist()[0]), encoding="utf-8",
                                errors="replace")
    return open(path_or_bytes, encoding="utf-8", errors="replace")

def fetch_latest_export_url() -> str:
    import httpx
    txt = httpx.get(LASTUPDATE_URL, timeout=30).text
    for line in txt.splitlines():                     # "<size> <md5> <url>.export.CSV.zip"
        if line.strip().endswith(".export.CSV.zip"):
            return line.split()[-1]
    raise RuntimeError("no export url in lastupdate.txt")

def ingest(source, sink: RawEventSink, bus=None) -> dict:
    """Parse -> (optional) publish to ingest.raw.gdelt -> land in raw_events.
    Dual-write is safe: the normalize consumer's insert dedups on (source, source_id)."""
    events, quality = parse_export(read_batch(source))
    res = {}
    if bus is not None:
        from services.ingest_common.bus import TOPIC_RAW_GDELT
        res["published"] = bus.publish(TOPIC_RAW_GDELT, events, producer="ingest_gdelt")
    res.update(sink.insert_many(events))
    res.update(quality)
    res["gdelt_total"] = sink.count("gdelt")
    return res

def run_once(file: str | None, sink: RawEventSink, bus=None) -> dict:
    if file:
        return ingest(file, sink, bus)
    import httpx
    url = fetch_latest_export_url()
    data = httpx.get(url, timeout=120).content
    out = ingest(data, sink, bus)
    out["batch_url"] = url
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", help="local export .zip/.csv (offline batch)")
    ap.add_argument("--once", action="store_true", help="fetch latest live batch once")
    ap.add_argument("--loop", action="store_true", help="poll every --interval seconds")
    ap.add_argument("--interval", type=int, default=900)
    ap.add_argument("--publish", action="store_true",
                    help="also publish to the event bus (ingest.raw.gdelt)")
    args = ap.parse_args()
    sink = RawEventSink()
    bus = None
    if args.publish:
        from services.ingest_common.bus import get_bus
        bus = get_bus()
    if args.loop:
        while True:
            try:
                print(time.strftime("%H:%M:%S"), run_once(None, sink, bus))
            except Exception as ex:                    # keep polling through feed hiccups
                print("WARN batch failed:", ex)
            time.sleep(args.interval)
    else:
        print(run_once(args.file if args.file else None, sink, bus))

if __name__ == "__main__":
    main()
