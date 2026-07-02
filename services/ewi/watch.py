"""Task 63 — EWI watch service: machine rules over series/raw_events -> ewi.alerts.

Concrete, machine-checkable counterparts of the Phase-11 indicator board.
Edge-triggered: an alert fires when a rule first crosses (rising edge) and
re-arms only after it clears — no alert spam on every poll. State checkpoint
lives next to the bus spool.

Alert envelope payload:
  {indicator, severity, value, threshold, message, fired_at}

CLI: python -m services.ewi.watch --once | --loop [--interval 60]
"""
from __future__ import annotations
import argparse, json, os, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from services.ingest_common.bus import get_bus, FileBus
from services.ingest_common.series import SeriesStore
from services.ingest_common.sink import RawEventSink
from services.question_registry.resolver import _fetch_event_ts

TOPIC_ALERTS = "ewi.alerts"

WATCH_RULES = [
    {"indicator": "Brent level", "kind": "series_level", "series": "brent_usd",
     "op": ">", "threshold": 110.0, "severity": "high",
     "message": "Brent above $110 — escalation-pricing regime"},
    {"indicator": "Brent day-jump", "kind": "series_jump", "series": "brent_usd",
     "window_s": 7 * 86400, "jump_pct": 8.0, "severity": "high",
     "message": "Brent jumped >8% within a week — shock onset signature"},
    {"indicator": "Iran battle tempo", "kind": "event_rate", "source": "acled",
     "event_types": ["battles", "explosions_remote_violence"], "countries": ["Iran"],
     "window_days": 7, "threshold": 5, "severity": "critical",
     "message": ">=5 battle events in Iran within 7d — kinetic tempo threshold"},
    {"indicator": "Gulf shipping attacks", "kind": "event_rate", "source": "acled",
     "event_types": ["explosions_remote_violence"], "countries": ["UAE", "Kuwait",
     "Saudi Arabia", "Bahrain"], "window_days": 14, "threshold": 3,
     "severity": "high", "message": ">=3 maritime/territory attacks on Gulf states in 14d"},
]


def evaluate_rule(rule: dict, ser: SeriesStore, snk: RawEventSink,
                  now: float) -> tuple[bool, float | None]:
    """-> (breached, observed_value)."""
    if rule["kind"] == "series_level":
        v = ser.value_asof(rule["series"], now)
        if v is None:
            return False, None
        ops = {">": v > rule["threshold"], "<": v < rule["threshold"]}
        return ops[rule["op"]], v
    if rule["kind"] == "series_jump":
        v_now = ser.value_asof(rule["series"], now)
        v_then = ser.value_asof(rule["series"], now - rule["window_s"])
        if not v_now or not v_then:
            return False, None
        pct = 100 * (v_now - v_then) / v_then
        return pct > rule["jump_pct"], round(pct, 2)
    if rule["kind"] == "event_rate":
        ts = _fetch_event_ts(snk, rule, now - rule["window_days"] * 86400, now)
        return len(ts) >= rule["threshold"], len(ts)
    return False, None


def _state_path(bus) -> str | None:
    return os.path.join(bus.root, "ewi.state.json") if isinstance(bus, FileBus) else \
        os.path.join("/tmp/argus", "ewi.state.json")


def watch_once(ser: SeriesStore | None = None, snk: RawEventSink | None = None,
               bus=None, now: float | None = None,
               rules: list[dict] | None = None) -> dict:
    ser = ser or SeriesStore(); snk = snk or RawEventSink(); bus = bus or get_bus()
    now = now or time.time()
    rules = rules if rules is not None else WATCH_RULES
    sp = _state_path(bus)
    state = {}
    if sp and os.path.exists(sp):
        with open(sp) as f:
            state = json.load(f)
    fired, cleared, active = [], [], []
    for rule in rules:
        breached, value = evaluate_rule(rule, ser, snk, now)
        was = state.get(rule["indicator"], False)
        if breached and not was:                       # rising edge -> fire once
            alert = {"indicator": rule["indicator"], "severity": rule["severity"],
                     "value": value, "threshold": rule.get("threshold") or
                     rule.get("jump_pct"), "message": rule["message"],
                     "fired_at": now, "source_id": f"{rule['indicator']}|{int(now)}"}
            bus.publish(TOPIC_ALERTS, [alert], producer="ewi-watch")
            fired.append(alert)
        elif not breached and was:
            cleared.append(rule["indicator"])
        if breached:
            active.append(rule["indicator"])
        state[rule["indicator"]] = breached
    if sp:
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        with open(sp, "w") as f:
            json.dump(state, f)
    return {"checked": len(rules), "fired": fired, "cleared": cleared,
            "active": active, "ts": now}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()
    if args.loop:
        while True:
            print(time.strftime("%H:%M:%S"), json.dumps(watch_once(), default=str))
            time.sleep(args.interval)
    else:
        print(json.dumps(watch_once(), indent=1, default=str))


if __name__ == "__main__":
    main()
