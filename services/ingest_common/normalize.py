"""ARGUS ingestion — normalize consumer (Task 46).

Drains ingest.raw.* from the bus, VALIDATES against the ingestion contract,
ENRICHES with an analytic domain, lands valid events in raw_events (dedup),
and re-publishes the enriched envelope to ingest.normalized.

Checkpointed offsets (file-bus mode) live next to the spool, so repeated runs
only process new messages; Kafka mode would use consumer groups instead.

CLI:
  python -m services.ingest_common.normalize --once          # drain available
  python -m services.ingest_common.normalize --loop [--interval 60]
"""
from __future__ import annotations
import argparse, json, os, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.ingest_common.bus import (get_bus, RAW_TOPICS, TOPIC_NORMALIZED, FileBus)
from services.ingest_common.sink import RawEventSink

REQUIRED = ("source", "source_id", "event_type", "occurred_at")
MAX_FUTURE_S = 2 * 86400          # events may not be >2 days in the future

# event_type -> analytic domain (blueprint seven-domain schema)
DOMAIN_MAP = {
    # security
    "battles": "security", "explosions_remote_violence": "security",
    "violence_against_civilians": "security", "fight": "security",
    "assault": "security", "coerce": "security", "exhibit_force_posture": "security",
    "unconventional_mass_violence": "security", "threaten": "security",
    "reduce_relations": "security",
    # social
    "protests": "social", "riots": "social", "protest": "social",
    # political
    "strategic_developments": "political", "public_statement": "political",
    "appeal": "political", "consult": "political", "demand": "political",
    "disapprove": "political", "reject": "political", "investigate": "political",
    "yield": "political", "express_intent_cooperate": "political",
    "diplomatic_cooperation": "political",
    # economic
    "provide_aid": "economic", "material_cooperation": "economic",
}

def validate_event(e: dict) -> tuple[bool, str]:
    for k in REQUIRED:
        if not e.get(k):
            return False, f"missing:{k}"
    try:
        occ = float(e["occurred_at"])
    except (TypeError, ValueError):
        return False, "occurred_at:not_numeric"
    if occ < 0 or occ > time.time() + MAX_FUTURE_S:
        return False, "occurred_at:out_of_range"
    c = e.get("confidence")
    if c is not None and not (0.0 <= float(c) <= 1.0):
        return False, "confidence:out_of_range"
    h = e.get("h3_cell")
    if h is not None and not isinstance(h, str):
        return False, "h3_cell:not_str"
    return True, ""

def enrich(e: dict) -> dict:
    e = dict(e)
    e["domain"] = DOMAIN_MAP.get(e.get("event_type", ""), "political")
    payload = dict(e.get("payload") or {})
    payload["domain"] = e["domain"]
    e["payload"] = payload
    return e

# ----------------------------------------------------------------- consumer --
def _ckpt_path(bus) -> str | None:
    return os.path.join(bus.root, "normalize.checkpoints.json") if isinstance(bus, FileBus) else None

def _load_ckpt(bus) -> dict:
    p = _ckpt_path(bus)
    if p and os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}

def _save_ckpt(bus, ck: dict):
    p = _ckpt_path(bus)
    if p:
        with open(p, "w") as f:
            json.dump(ck, f)

def consume_once(bus=None, sink: RawEventSink | None = None) -> dict:
    bus = bus or get_bus()
    sink = sink or RawEventSink()
    ck = _load_ckpt(bus)
    now = time.time()
    stats: dict = {}
    for src, topic in RAW_TOPICS.items():
        offset = int(ck.get(topic, 0))
        envs = bus.read(topic, offset=offset)
        valid, invalid_reasons = [], {}
        max_lag = 0.0
        for env in envs:
            e = env.get("payload") or {}
            ok, reason = validate_event(e)
            if ok:
                valid.append(enrich(e))
            else:
                invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
            max_lag = max(max_lag, now - float(env.get("ts") or now))
        res = sink.insert_many(valid) if valid else {"received": 0, "inserted": 0,
                                                     "duplicates": 0}
        published = bus.publish(TOPIC_NORMALIZED, valid, producer="normalize") if valid else 0
        ck[topic] = offset + len(envs)
        stats[topic] = {"read": len(envs), "valid": len(valid),
                        "invalid": sum(invalid_reasons.values()),
                        "invalid_reasons": invalid_reasons,
                        "inserted": res["inserted"], "duplicates": res["duplicates"],
                        "published_normalized": published,
                        "max_lag_s": round(max_lag, 1)}
    _save_ckpt(bus, ck)
    stats["normalized_depth"] = bus.depth(TOPIC_NORMALIZED) if isinstance(bus, FileBus) else None
    return stats

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()
    if args.loop:
        while True:
            print(time.strftime("%H:%M:%S"), json.dumps(consume_once()))
            time.sleep(args.interval)
    else:
        print(json.dumps(consume_once(), indent=1))

if __name__ == "__main__":
    main()
