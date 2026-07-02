"""Task 83 — full-fidelity band service.

Nightly job: compute the adversary+conformal robust bands at FULL fidelity
(ARGUS_FAST=0 path: more probes, more paths) for the deployed theta, and cache
them to the store (PostgreSQL when DATABASE_URL is set). The API then serves these
full-fidelity bands even when it boots in fast mode (engines._load_or_compute_bands).

SLO: the refresh must finish within the budget (default 2h). The job exits non-zero
if it overruns so the CronJob/alert surfaces it.

    python -m workers.bands.refresh                 # full fidelity, 2h budget
    python -m workers.bands.refresh --fast           # small (dev/CI/tests)
    python -m workers.bands.refresh --budget-seconds 7200 --n-paths 3000 --n-probe 20
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import numpy as np
from core.engine import WorldEngine, THETA_NAMES
from services.copilot.config import get_settings
from services.copilot.engines import compute_bands
from services.copilot.store import get_store


def _load_theta() -> np.ndarray:
    """Deployed theta: promoted champion → file cache → train (same precedence as engines)."""
    try:
        row = get_store().theta_promoted()
        if row and list(row["names"]) == THETA_NAMES:
            return np.array([float(v) for v in row["vals"]])
    except Exception:
        pass
    cache = get_settings().theta_cache
    if os.path.exists(cache):
        d = json.load(open(cache))
        if d.get("names") == THETA_NAMES:
            return np.array(d["theta"])
    from novelty.cassandra import CalibrationTrainer, transfer_theta
    tr = CalibrationTrainer(n_paths=2500)
    return transfer_theta(tr.train(iters=40, verbose=False))


def refresh(fast: bool = False, n_probe: int | None = None, n_paths: int | None = None,
            budget_seconds: float = 7200.0) -> dict:
    from services.kg.gate import gate_theta              # Task 57: same gate as engines
    seed = get_settings().seed
    n_probe = n_probe if n_probe is not None else (6 if fast else 20)
    n_paths = n_paths if n_paths is not None else (1200 if fast else 3000)

    t0 = time.time()
    theta, _ = gate_theta(_load_theta())
    theta_hash = hashlib.sha256(np.round(theta, 6).tobytes()).hexdigest()[:12]
    eng = WorldEngine(theta=theta, seed=seed)
    bands = compute_bands(theta, eng, n_probe=n_probe, n_paths=n_paths)
    elapsed = time.time() - t0

    fidelity = "fast" if fast else "full"
    store = get_store()
    store.bands_save(theta_hash, bands, n_paths, fidelity)
    try:
        store.record_run(f"bands-{theta_hash}", "bands",
                         {"keys": list(bands), "n_paths": n_paths, "n_probe": n_probe,
                          "fidelity": fidelity, "elapsed_s": round(elapsed, 1)},
                         theta_hash, seed)
    except Exception:
        pass

    within = elapsed <= budget_seconds
    report = {"theta_hash": theta_hash, "n_keys": len(bands), "n_paths": n_paths,
              "fidelity": fidelity, "elapsed_s": round(elapsed, 2),
              "budget_s": budget_seconds, "within_budget": within,
              "backend": get_settings().backend}
    print(json.dumps(report))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh full-fidelity bands into the store")
    ap.add_argument("--fast", action="store_true", help="small ensemble (dev/CI/tests)")
    ap.add_argument("--n-probe", type=int, default=None)
    ap.add_argument("--n-paths", type=int, default=None)
    ap.add_argument("--budget-seconds", type=float, default=7200.0)
    a = ap.parse_args()
    rep = refresh(fast=a.fast, n_probe=a.n_probe, n_paths=a.n_paths,
                  budget_seconds=a.budget_seconds)
    if not rep["within_budget"]:
        print(f"BANDS REFRESH OVERRAN BUDGET: {rep['elapsed_s']}s > {rep['budget_s']}s",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
