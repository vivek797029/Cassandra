"""Smoke tests: python tests/test_smoke.py (no pytest dependency needed)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
from core.engine import (WorldEngine, THETA_DEFAULT, THETA_LO, THETA_HI,
                         event_probs, replay_event_probs, RESOLVED_EVENTS)
from core.phases import load_situation, ScenarioEngine
from novelty.cassandra import (CalibrationTrainer, Adversary, ConformalLayer,
                               InterventionSearch, brier, to_z, to_theta)

def t(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    assert cond, name

# engine determinism + shapes
e = WorldEngine(THETA_DEFAULT, seed=42)
s1 = e.simulate(N=500, Q=8, seed=1); s2 = e.simulate(N=500, Q=8, seed=1)
t("deterministic under seed", np.allclose(s1["oil"], s2["oil"]))
t("shapes", s1["oil"].shape == (500, 8) and s1["me"].shape == (500, 8))
t("regimes valid", set(np.unique(s1["me"])) <= {0,1,2,3})

# probabilities sane
ev = event_probs(e.simulate(N=2000, Q=40, seed=3))
t("probs in [0,1]", all(v is None or 0 <= v <= 1 for v in ev.values()))
t("monotone horizons", ev["ME_war_180d"] <= ev["ME_war_1y"] <= ev["ME_war_3y"])

# replay + calibration improves (or at least never worsens materially)
preds, outs = replay_event_probs(e, N=1500, seed=7)
b0 = brier(preds, outs)
tr = CalibrationTrainer(n_paths=800)
theta = tr.train(iters=8, verbose=False)
p1, _ = replay_event_probs(WorldEngine(theta), N=1500, seed=7)
b1 = brier(p1, outs)
t(f"calibration not worse (b0={b0:.4f} b1={b1:.4f})", b1 <= b0 + 0.01)

# theta transforms
z = to_z(THETA_DEFAULT)
t("z in [0,1]", (z >= 0).all() and (z <= 1).all())
t("roundtrip", np.allclose(to_theta(z), THETA_DEFAULT))

# adversary bands contain center
adv = Adversary(THETA_DEFAULT, n_probe=4, n_paths=800, Q=8)
bands = adv.bands(["ME_war_1y", "Brent_gt120_1y"])
t("band contains center", all(b["lo"] <= b["center"] <= b["hi"] for b in bands.values()))

# conformal widens
cf = ConformalLayer(e, n_paths=800)
w = cf.widen({"lo": 0.4, "hi": 0.5, "center": 0.45})
t("conformal widens", w["lo"] <= 0.4 and w["hi"] >= 0.5)

# interventions reduce harm
isr = InterventionSearch(THETA_DEFAULT, n_paths=800, Q=8)
res = isr.greedy()
t("portfolio reduces harm", res["portfolio_harm"] <= res["base_harm"])
t("budget respected", res["spent"] <= res["budget"] + 1e-9)

# phases
situ = load_situation()
t("situation has facts+signals", len(situ["facts"]) >= 10 and len(situ["signals"]) >= 10)
sc = ScenarioEngine(e.simulate(N=1500, Q=12, seed=5)).cluster(k=4)
t("4 scenarios, shares sum ~1", abs(sum(c["share"] for c in sc["clusters"]) - 1) < 0.01)

print("\nALL TESTS PASSED")
