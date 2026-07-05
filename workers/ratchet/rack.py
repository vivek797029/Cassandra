"""Task 94 — frozen-baseline rack + ratchet regression gate.

Every release freezes its champion theta into a persistent rack. The rack is
RE-SCORED on the frozen replay set on every run ("re-scored forever"), and the
ratchet gate fails if a candidate theta scores WORSE (higher Brier) than the best
frozen ancestor — so no release silently regresses. Deterministic: fixed CRN seed.

    python -m workers.ratchet.rack --freeze v2.0.0   # freeze the deployed champion
    python -m workers.ratchet.rack --gate            # re-score + gate the deployed theta
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
from core.engine import WorldEngine, THETA_NAMES
from novelty.cassandra import CalibrationTrainer, brier, transfer_theta

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TOL = 0.005


def rack_path() -> str:
    return os.environ.get("ARGUS_BASELINE_RACK", os.path.join(_ROOT, "data", "baseline_rack.json"))


def _hash(theta) -> str:
    return hashlib.sha256(np.round(np.asarray(theta, float), 6).tobytes()).hexdigest()[:12]


def frozen_brier(theta, n_paths: int = 1200, seed: int = 7) -> float:
    """Brier of a theta on the FROZEN built-in replay set (deterministic)."""
    tr = CalibrationTrainer(n_paths=n_paths, events=None)     # None → frozen RESOLVED_EVENTS
    preds, outs = tr._probs(WorldEngine(theta=np.asarray(theta, float)), seed)
    return float(brier(preds, outs))


def load_rack(path: str | None = None) -> list[dict]:
    p = path or rack_path()
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_rack(rack: list[dict], path: str | None = None) -> None:
    p = path or rack_path()
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rack, f, indent=2)


def freeze_baseline(release: str, theta, n_paths: int = 1200, path: str | None = None) -> dict:
    theta = [float(x) for x in np.asarray(theta, float)]
    h = _hash(theta)
    rack = load_rack(path)
    if any(e["theta_hash"] == h for e in rack):
        return next(e for e in rack if e["theta_hash"] == h)
    entry = {"release": release, "theta_hash": h, "theta": theta,
             "frozen_brier": round(frozen_brier(theta, n_paths), 6)}
    rack.append(entry)
    save_rack(rack, path)
    return entry


def rescore(n_paths: int = 1200, path: str | None = None) -> list[dict]:
    """Re-score every frozen baseline on the current frozen set (forever)."""
    out = []
    for e in load_rack(path):
        out.append({"release": e["release"], "theta_hash": e["theta_hash"],
                    "frozen_brier": e.get("frozen_brier"),
                    "brier_now": round(frozen_brier(e["theta"], n_paths), 6)})
    return out


def regression_gate(candidate_theta, tol: float = TOL, n_paths: int = 1200,
                    path: str | None = None) -> dict:
    scored = rescore(n_paths, path)
    cand = round(frozen_brier(candidate_theta, n_paths), 6)
    if not scored:
        return {"pass": True, "candidate_brier": cand, "best_ancestor": None,
                "best_ancestor_brier": None, "reason": "empty rack"}
    best = min(scored, key=lambda x: x["brier_now"])
    passed = cand <= best["brier_now"] + tol
    return {"pass": bool(passed), "candidate_brier": cand,
            "best_ancestor": best["release"], "best_ancestor_brier": best["brier_now"],
            "delta": round(cand - best["brier_now"], 6), "tol": tol}


def _deployed_theta():
    """Deployed champion: promoted-db → file cache → deterministic train (CI fallback)."""
    try:
        from services.copilot.store import get_store
        row = get_store().theta_promoted()
        if row and list(row["names"]) == THETA_NAMES:
            return np.array([float(v) for v in row["vals"]])
    except Exception:
        pass
    cache = os.path.join(_ROOT, "output", "theta_deployed.json")
    if os.path.exists(cache):
        d = json.load(open(cache))
        if d.get("names") == THETA_NAMES:
            return np.array(d["theta"])
    return transfer_theta(CalibrationTrainer(n_paths=1500).train(iters=20, verbose=False))


def main() -> int:
    ap = argparse.ArgumentParser(description="Frozen-baseline rack / ratchet gate")
    ap.add_argument("--freeze", metavar="RELEASE", help="freeze the deployed champion as RELEASE")
    ap.add_argument("--gate", action="store_true", help="re-score rack + gate the deployed theta")
    a = ap.parse_args()
    if a.freeze:
        e = freeze_baseline(a.freeze, _deployed_theta())
        print(f"frozen {a.freeze}: {e['theta_hash']} brier={e['frozen_brier']}")
        return 0
    print(json.dumps(rescore(), indent=2))
    if a.gate:
        r = regression_gate(_deployed_theta())
        print(json.dumps(r, indent=2))
        print("RATCHET:", "PASS" if r["pass"] else "REGRESSION")
        return 0 if r["pass"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
