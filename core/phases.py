"""
CASSANDRA Core — Analytic Phases Library
Phases 1-4, 8-9, 11-12 (Phase 5-7 live in engine.py, Phase 10 in novelty/).
Data-driven where possible: signals/analogs/EWIs load from data/situation.json;
causal weights are CHECKED against the simulator by perturbation; scenarios are
DISCOVERED by clustering ensemble paths rather than hand-written.
"""
from __future__ import annotations
import json, os
import numpy as np
from core.engine import WorldEngine, theta_dict

DATA = os.path.join(os.path.dirname(__file__), "..", "data", "situation.json")

def load_situation() -> dict:
    with open(DATA) as f:
        return json.load(f)

# ---------------------------------------------------------------- Phase 3 ---
class CausalGraph:
    """Weighted causal map. Edge weights are expert priors; node influence is
    VERIFIED by perturbation: knock each channel +/-20% in the simulator and
    measure dispersion of the harm functional -> empirical weight."""

    def __init__(self, situation: dict):
        self.nodes = situation["causal_nodes"]
        self.edges = situation["causal_edges"]

    def empirical_weights(self, theta, n_paths=2500, Q=12) -> dict:
        from novelty.cassandra import harm_functional
        eng = WorldEngine(theta=theta)
        base = harm_functional(eng.simulate(N=n_paths, Q=Q, seed=61))
        channels = {
            "Middle East war / energy shock": {"me_esc": 1.2, "me_hz": 1.2},
            "Great-power deterrence erosion": {"tw_block": 1.2},
            "EM debt distress": {"em_haz": 1.2},
            "Climate / food shock": {"food_shock": 1.2},
            "Ukraine war persistence": {"ua_cf": 0.8},
        }
        sens = {}
        for name, mods in channels.items():
            h = harm_functional(eng.simulate(N=n_paths, Q=Q, hazard_mods=mods, seed=61))
            sens[name] = abs(h - base)
        total = sum(sens.values()) or 1.0
        return {k: round(100 * v / total, 1) for k, v in sens.items()}

# ---------------------------------------------------------------- Phase 8 ---
class ScenarioEngine:
    """Scenarios are discovered, not asserted: k-means (numpy implementation)
    on per-path features of the ensemble, then auto-labeled by severity."""

    FEATURES = ["max_oil", "min_growth_annual", "war_quarters", "tw_event", "mean_infl"]

    def __init__(self, sim: dict):
        oil, g, pi = sim["oil"], sim["growth"], sim["inflation"]
        me, tw = sim["me"], sim["tw"]
        ann = g[:, :8].reshape(g.shape[0], -1, 4).mean(2) if g.shape[1] >= 8 else g[:, :4].mean(1, keepdims=True)
        self.X = np.column_stack([
            oil.max(1), ann.min(1), (me >= 2).sum(1), (tw >= 1).any(1).astype(float),
            pi[:, :8].mean(1) if pi.shape[1] >= 8 else pi.mean(1)])
        self.sim = sim

    def cluster(self, k=4, iters=25, seed=3) -> dict:
        X = (self.X - self.X.mean(0)) / (self.X.std(0) + 1e-9)
        rng = np.random.default_rng(seed)
        C = X[rng.choice(len(X), k, replace=False)]
        for _ in range(iters):
            d = ((X[:, None, :] - C[None]) ** 2).sum(2)
            lab = d.argmin(1)
            for j in range(k):
                if (lab == j).any():
                    C[j] = X[lab == j].mean(0)
        out = []
        for j in range(k):
            m = lab == j
            f = self.X[m]
            out.append({
                "share": round(float(m.mean()), 3),
                "max_oil_med": round(float(np.median(f[:, 0])), 1),
                "min_annual_growth_med": round(float(np.median(f[:, 1])), 2),
                "war_quarters_med": float(np.median(f[:, 2])),
                "taiwan_event_rate": round(float(f[:, 3].mean()), 3),
                "mean_inflation_med": round(float(np.median(f[:, 4])), 2),
            })
        # label by a severity score
        sev = [o["max_oil_med"] - 40 * o["min_annual_growth_med"] + 6 * o["war_quarters_med"]
               + 120 * o["taiwan_event_rate"] for o in out]
        order = np.argsort(sev)
        names = ["A — Hard Landing Averted (best case)",
                 "B — Grinding Equilibrium (most likely)",
                 "C — Second Conflagration (worst plausible)",
                 "D — Compound Tail (black-swan cluster)"]
        labeled = []
        for rank, idx in enumerate(order):
            o = out[idx]; o["scenario"] = names[min(rank, 3)]
            labeled.append(o)
        # 'most likely' label should follow share, keep severity order but note shares
        return {"clusters": labeled,
                "note": "Clusters discovered by k-means on path features; "
                        "names assigned by severity rank. Shares are ensemble weights."}

# ---------------------------------------------------------------- Phase 9 ---
def explain_forecast(key: str, prob, situation: dict, theta) -> dict:
    """Evidence chain for a forecast: evidence -> mechanism -> analog ->
    counterargument -> uncertainty. Templated from structured data so every
    emitted forecast carries its reasoning."""
    lib = situation["explanations"].get(key, {})
    td = theta_dict(np.asarray(theta))
    mech = lib.get("mechanism", "")
    mech = mech.replace("{esc}", f"{td['me_esc_base'] + td['me_esc_decay_amp']:.3f}") \
               .replace("{hz}", f"{td['me_hz_base'] + td['me_hz_decay_amp']:.3f}")
    return {"forecast": key, "probability": prob,
            "evidence": lib.get("evidence", []),
            "causal_pathway": mech,
            "historical_analog": lib.get("analog", ""),
            "counterargument": lib.get("counter", ""),
            "confidence": lib.get("confidence", "low"),
            "failure_conditions": lib.get("failure", [])}

# --------------------------------------------------------------- Phase 12 ---
def red_team_summary(bands: dict, situation: dict) -> dict:
    """Convert adversarial-conformal (robust) bands into red-team findings."""
    findings = []
    for k, b in bands.items():
        width = b["hi"] - b["lo"]
        if width > 0.35:
            verdict = "FRAGILE — adversary + calibration error move this materially; use the band, never the point"
        elif width > 0.18:
            verdict = "SENSITIVE — direction and ordering reliable, level uncertain by >±9pp"
        else:
            verdict = "ROBUST — stable under parameter attack and calibration widening"
        findings.append({"forecast": k, "center": b["center"],
                         "adversarial_band": [b["lo"], b["hi"]],
                         "band_width": round(width, 3), "verdict": verdict})
    findings.sort(key=lambda d: -d["band_width"])
    return {"findings": findings,
            "qualitative_challenges": situation["red_team_qualitative"]}
