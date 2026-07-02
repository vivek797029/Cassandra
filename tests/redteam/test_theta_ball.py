"""Task 65 — red-team CI gate: theta-ball decision-flip rate.

Attack: extremize each headline forecast over the plausibility ball
||dz|| <= rho in normalized theta space (the production Adversary, CRN seeds).
Metric: DECISION-FLIP RATE — fraction of headline keys whose adversarial band
crosses the 50% action line (i.e. a defensible parameterization reverses the
directional call). GATE: flip rate <= 2/6 at rho=0.10. A model whose calls
flip under modest parameter attack must not ship.
Deterministic: fixed seeds, fixed probe count.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from core.engine import THETA_DEFAULT
from novelty.cassandra import Adversary, transfer_theta, CalibrationTrainer

HEADLINE_KEYS = ["ME_war_1y", "Hormuz_closure_by_end2027",
                 "UA_formal_ceasefire_by_end2027", "Brent_gt120_1y",
                 "Global_recession_lt2p5_by_2028", "Inflation_gt5_2027avg"]
MAX_FLIP_RATE = 2 / 6 + 1e-9


def _deployed_theta():
    tr = CalibrationTrainer(n_paths=600)
    return transfer_theta(tr.train(iters=4, verbose=False))


def test_decision_flip_rate_under_theta_ball_attack():
    theta = _deployed_theta()
    adv = Adversary(theta, rho=0.10, n_probe=8, n_paths=1200, Q=12, seed=5)
    bands = adv.bands(HEADLINE_KEYS)
    flips, detail = 0, {}
    for k, b in bands.items():
        crossed = b["lo"] < 0.5 < b["hi"]
        flips += crossed
        detail[k] = {"center": b["center"], "band": [b["lo"], b["hi"]],
                     "decision_flip": crossed}
    rate = flips / len(bands)
    print(f"\ntheta-ball decision-flip rate: {rate:.2f} ({flips}/{len(bands)})")
    for k, d in detail.items():
        print(f"  {k:34s} {d['center']:.2f} [{d['band'][0]:.2f},{d['band'][1]:.2f}]"
              f" {'FLIP' if d['decision_flip'] else 'stable'}")
    assert rate <= MAX_FLIP_RATE, f"flip rate {rate:.2f} exceeds gate {MAX_FLIP_RATE:.2f}: {detail}"


def test_bands_widen_monotonically_with_rho():
    """Sanity on the attack itself: a bigger ball must never shrink the band."""
    theta = _deployed_theta()
    keys = HEADLINE_KEYS[:3]
    small = Adversary(theta, rho=0.05, n_probe=6, n_paths=800, Q=8, seed=5).bands(keys)
    large = Adversary(theta, rho=0.15, n_probe=6, n_paths=800, Q=8, seed=5).bands(keys)
    for k in keys:
        w_s = small[k]["hi"] - small[k]["lo"]
        w_l = large[k]["hi"] - large[k]["lo"]
        assert w_l >= w_s - 0.02, (k, w_s, w_l)
