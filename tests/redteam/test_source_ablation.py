"""Task 67 — red-team CI gate: source-family ablation.

Attack: remove an entire evidence family from the training set (poisoning /
loss-of-feed proxy) and retrain. Metric: max displacement of the headline
forward forecasts vs full-data training. GATE: no single family may move any
headline probability by more than 0.15 — no feed is allowed to be
load-bearing (blueprint B8).
Families over the built-in replay event set:
  oil      = Brent threshold events
  conflict = regime-state events (ceasefire/war/settlement/Taiwan/Ukraine)
  macro    = growth/inflation events
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

import numpy as np
from core.engine import RESOLVED_EVENTS, WorldEngine, event_probs
from novelty.cassandra import CalibrationTrainer, transfer_theta

HEADLINE_KEYS = ["ME_war_1y", "Hormuz_closure_by_end2027", "Brent_gt120_1y",
                 "Global_recession_lt2p5_by_2028"]
MAX_DISPLACEMENT = 0.15

FAMILY_OF = {
    "Hormuz closed within 2q of war": "conflict",
    "Brent >$120 within 2q": "oil",
    "Ceasefire reached within 2q": "conflict",
    "Oil back <$100 at end of 2q": "oil",
    "H1 mean growth <3.2": "macro",
    "H1 mean inflation >4.2": "macro",
    "Taiwan blockade in H1": "conflict",
    "Ukraine ceasefire by Jun": "conflict",
    "Brent >$150 in H1": "oil",
    "ME fully settled by Jun": "conflict",
}


def _train(events) -> np.ndarray:
    tr = CalibrationTrainer(n_paths=600, events=events)
    return transfer_theta(tr.train(iters=6, verbose=False))


def _forward(theta) -> dict:
    sim = WorldEngine(theta, seed=42).simulate(N=2000, Q=12, seed=42)
    ev = event_probs(sim)
    return {k: ev[k] for k in HEADLINE_KEYS if ev.get(k) is not None}


def test_no_source_family_is_load_bearing():
    full_theta = _train(None)                          # full built-in set
    base = _forward(full_theta)
    worst = {}
    for family in ("oil", "conflict", "macro"):
        ablated = [e for e in RESOLVED_EVENTS if FAMILY_OF[e[0]] != family]
        assert len(ablated) < len(RESOLVED_EVENTS)     # family actually removed
        theta_a = _train(ablated)
        fwd = _forward(theta_a)
        disp = {k: abs(fwd[k] - base[k]) for k in base}
        worst[family] = max(disp.values())
        print(f"\nablate {family:9s}: max displacement "
              f"{worst[family]:.3f}  {dict((k, round(v, 3)) for k, v in disp.items())}")
        assert worst[family] <= MAX_DISPLACEMENT, (
            f"family '{family}' is load-bearing: {disp}")
    print("ablation gate PASS:", {k: round(v, 3) for k, v in worst.items()})
