"""Task 70 — graceful degradation.

The copilot must keep answering when the live forecasting engine is unavailable
(failed warm, OOM-killed worker, corrupt theta) instead of returning 500s. On
every healthy warm we persist a last-known-good read snapshot; if get_engines()
later raises, the API serves that snapshot through `SnapshotSource` and stamps
every answer with a staleness banner. Live-compute endpoints (counterfactual,
policy, jobs) return 503 rather than pretending — there is no honest cached
answer for a simulation that never ran.
"""
from __future__ import annotations
import os, json, time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def snapshot_path() -> str:
    return os.environ.get(
        "ARGUS_SNAPSHOT", os.path.join(ROOT, "output", "last_good_snapshot.json"))


def save_snapshot(engines) -> str:
    """Persist a last-known-good read snapshot from a healthy engine (atomic)."""
    keys = [f["key"] for f in engines.all_forecasts()]
    snap = {
        "saved_at": time.time(),
        "theta_hash": getattr(engines, "theta_hash", "unknown"),
        "as_of": engines.situation.get("as_of"),
        "forecasts": engines.all_forecasts(),
        "explanations": {k: engines.explanation(k) for k in keys if engines.explanation(k)},
        "ewi": engines.ewi(),
        "fans": engines.fans,
        "scenarios": engines.scenarios,
        "analogs": engines.analogs(""),
        "facts": engines.facts(),
    }
    path = snapshot_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(snap, f, default=str)
    os.replace(tmp, path)
    return path


def load_snapshot() -> dict | None:
    path = snapshot_path()
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def staleness(snap: dict) -> dict:
    age = max(0.0, time.time() - float(snap.get("saved_at", 0) or 0))
    return {"degraded": True, "as_of": snap.get("as_of"),
            "cached_at": snap.get("saved_at"), "age_seconds": round(age, 1),
            "theta_hash": snap.get("theta_hash")}


def banner(snap: dict) -> str:
    st = staleness(snap)
    mins = int(st["age_seconds"] // 60)
    return ("> ⚠️ **Degraded mode — live forecasting engine unavailable.** Showing the "
            f"last validated snapshot (evidence as of {st['as_of']}, cached {mins} min ago). "
            "Numbers are stale and live what-if / policy simulation is paused.")


class SnapshotSource:
    """Read-only stand-in exposing the Engines *read* API from a saved snapshot.
    Compute methods are intentionally absent — callers must route those to 503."""
    degraded = True

    def __init__(self, snap: dict):
        self.snap = snap
        self.theta_hash = snap.get("theta_hash", "snapshot")
        self.seed = -1
        self.situation = {"as_of": snap.get("as_of")}
        self._fc = {f["key"]: f for f in snap.get("forecasts", [])}
        self.fans = snap.get("fans", {})
        self.scenarios = snap.get("scenarios", {})

    def all_forecasts(self) -> list[dict]:
        return list(self._fc.values())

    def forecast(self, key: str):
        return self._fc.get(key)

    def explanation(self, key: str):
        return self.snap.get("explanations", {}).get(key)

    def ewi(self) -> list[dict]:
        return self.snap.get("ewi", [])

    def facts(self) -> list[dict]:
        return self.snap.get("facts", [])

    def analogs(self, query: str = "") -> list[dict]:
        return self.snap.get("analogs", [])
