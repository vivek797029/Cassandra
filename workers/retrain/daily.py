"""Task 54 — nightly retrain worker (champion/challenger ratchet, blueprint §25).

Flow:
  1. Trigger: --force, or pending messages on engine.retrain.requests (bus).
  2. Build the training event set: registry-resolved events (Task 51) when
     >= MIN_EVENTS, else the built-in replay set — behind a leakage Firewall.
  3. Train challenger theta (SPSA + identifiability transfer).
  4. Evaluate champion (promoted theta) and challenger on the SAME event set
     with common random numbers.
  5. RATCHET: promote challenger only if its Brier <= champion's. Either way
     the version is saved to theta_versions; promotions also refresh the file
     cache so the API picks the champion up on next start/rollover.
  6. Publish a run record to engine.runs (bus) + store manifest.

CLI:  python -m workers.retrain.daily --force [--iters 40]
Cron: deploy/k8s/argus.yaml nightly-retrain CronJob.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
import numpy as np

from core.engine import WorldEngine, THETA_NAMES, replay_event_probs
from core.firewall import Firewall
from novelty.cassandra import (CalibrationTrainer, transfer_theta, brier,
                               load_registry_events)
from services.copilot.config import get_settings
from services.copilot.store import get_store
from services.question_registry.registry import QuestionRegistry
from services.ingest_common.bus import get_bus

TOPIC_REQ = "engine.retrain.requests"
TOPIC_RUNS = "engine.runs"
MIN_EVENTS = 20


def _hash(theta) -> str:
    return hashlib.sha256(np.round(theta, 6).tobytes()).hexdigest()[:12]


def pending_requests(bus) -> int:
    try:
        return bus.depth(TOPIC_REQ)
    except Exception:
        return 0


def run(force: bool = False, iters: int = 40, n_paths: int = 2000,
        store=None, reg: QuestionRegistry | None = None, bus=None,
        now: float | None = None) -> dict:
    store = store or get_store()
    reg = reg or QuestionRegistry()
    bus = bus or get_bus()
    now = now or time.time()
    if not force and pending_requests(bus) == 0:
        return {"skipped": True, "reason": "no retrain requests pending (use --force)"}

    # --- training set behind the firewall (cutoff = now: retro events only) ---
    fw = Firewall(cutoff_ts=now)
    events, meta, req_q = load_registry_events(reg)
    used = "registry"
    if len(events) < MIN_EVENTS:
        events, req_q, used = None, None, "builtin-replay"

    trainer = CalibrationTrainer(n_paths=n_paths, events=events, replay_Q=req_q)
    challenger = transfer_theta(trainer.train(iters=iters, verbose=False))
    from services.kg.gate import gate_theta              # Task 57: gate before promotion
    challenger, gate_report = gate_theta(challenger)
    ch_hash = _hash(challenger)

    # --- champion vs challenger on identical events + seeds --------------------
    champion_row = store.theta_promoted()
    def _brier(theta) -> float:
        p, y = replay_event_probs(WorldEngine(theta), N=n_paths, seed=7,
                                  events=events, Q=req_q)
        return brier(p, y)
    b_chal = _brier(challenger)
    b_champ = None
    if champion_row and list(champion_row["names"]) == THETA_NAMES:
        b_champ = _brier(np.array([float(v) for v in champion_row["vals"]]))

    store.theta_save(ch_hash, THETA_NAMES, [float(x) for x in challenger],
                     b_chal, f"retrain ({used}, {len(events or [])} events)")
    promoted = False
    if b_champ is None or b_chal <= b_champ + 1e-9:
        store.theta_promote(ch_hash)
        promoted = True
        cache = get_settings().theta_cache
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "w") as f:
            json.dump({"names": THETA_NAMES,
                       "theta": [float(x) for x in challenger],
                       "brier_after": b_chal}, f)

    report = {"skipped": False, "event_set": used,
              "gate_blocked": len(gate_report["blocked"]),
              "n_events": len(events) if events else 10,
              "challenger": ch_hash, "brier_challenger": round(b_chal, 5),
              "champion": champion_row["theta_hash"] if champion_row else None,
              "brier_champion": round(b_champ, 5) if b_champ is not None else None,
              "promoted": promoted,
              "firewall_lineage_reads": len(fw.lineage()), "ts": now}
    mid = hashlib.sha256(json.dumps(report, sort_keys=True, default=str)
                         .encode()).hexdigest()[:16]
    store.record_run(mid, "pipeline", {"job": "retrain", "report": report},
                     theta_hash=ch_hash, seed=7)
    try:
        bus.publish(TOPIC_RUNS, [{"source_id": mid, **report}], producer="retrain")
    except Exception:
        pass
    report["manifest_id"] = mid
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--iters", type=int, default=40)
    args = ap.parse_args()
    print(json.dumps(run(force=args.force, iters=args.iters), indent=1, default=str))


if __name__ == "__main__":
    main()
