"""
CASSANDRA — Calibration-Adversarial, Simulation-Supervised Architecture for
Networked Dynamics & Risk Analysis.
============================================================================
The research-novelty layer. Four ideas, each implemented and runnable:

(1) CALIBRATION-TRAINED SIMULATION (CalibrationTrainer)
    The entire world simulator is treated as a stochastic program theta -> p,
    and theta is trained END-TO-END on a proper scoring rule (Brier) against
    events that actually resolved (leakage-firewalled replay window).
    The simulator is non-differentiable (discrete regime draws), so we use
    SPSA (simultaneous-perturbation stochastic approximation): an unbiased
    two-sided gradient estimate in normalized parameter space, with common
    random numbers for variance reduction. Prior art trains FORECASTERS on
    scoring rules; here the scoring-rule gradient flows into the CAUSAL
    MECHANISM parameters (hazards, jumps, pass-throughs) themselves.

(2) ADVERSARIALLY ROBUST PROBABILITY BANDS (Adversary)
    A red-team search maximizes/minimizes each forecast probability over a
    plausibility ball ||delta||<=rho in normalized theta space (a tractable
    stand-in for a KL ball). The reported object is not a point probability
    but a MIN-MAX BAND: 'no parameter set a reasonable critic could defend
    moves this number outside [lo, hi]'. This operationalizes red-teaming as
    optimization rather than narrative.

(3) ADVERSARIAL-CONFORMAL WIDENING (ConformalLayer)
    Split conformal prediction applied to the calibration residuals of the
    resolved-event set, then composed WITH the adversarial band: final band =
    conformal-quantile widening of the min-max band. Coverage guarantee is
    exact only under exchangeability (which world events violate); we state
    it as a floor heuristic, not a theorem.

(4) AMORTIZED INTERVENTION SEARCH (InterventionSearch)
    Policy levers are typed do-operations on hazard channels with costs.
    Greedy submodular-style search over portfolios under a budget, scored by
    expected loss reduction on a weighted harm functional of the ensemble
    (recession-quarters, war-quarters, default events). Returns the ranked
    portfolio with marginal value per cost — Phase 10 as optimization.

Honesty note: with n=10 resolved events this is a demonstration of the
method, not a statistical validation. The architecture is the contribution;
scale (GDELT/ICEWS-sized event sets) is future work — see README.
"""
from __future__ import annotations
import numpy as np
from core.engine import (WorldEngine, THETA_DEFAULT, THETA_LO, THETA_HI, THETA_NAMES,
                         clip_theta, replay_event_probs, event_probs, WorldState)

EPS = 1e-6

def brier(preds: np.ndarray, outs: np.ndarray, w=None) -> float:
    w = np.ones_like(preds) if w is None else w
    return float(np.average((preds - outs) ** 2, weights=w))

def log_score(preds, outs):
    p = np.clip(preds, 1e-4, 1 - 1e-4)
    return float(-np.mean(outs * np.log(p) + (1 - outs) * np.log(1 - p)))

# normalized coords: theta = lo + z*(hi-lo), z in [0,1]^d
to_z = lambda th: (th - THETA_LO) / (THETA_HI - THETA_LO)
to_theta = lambda z: THETA_LO + np.clip(z, 0, 1) * (THETA_HI - THETA_LO)

# ---------------------------------------------------------------------------
# Identifiability-aware parameter transfer (training regime != deployment regime)
# ---------------------------------------------------------------------------
# The replay window starts in ACTIVE WAR, so it identifies war-state mechanics
# (war->Hormuz hazard, oil jumps, war de-escalation, pass-throughs) strongly,
# but ceasefire-state hazards only weakly (selection effect: an escalation-heavy
# window would otherwise bias forward forecasts up). Identified params keep
# trained values; weakly identified ones shrink toward the expert prior.
IDENTIFIED = {"me_war_hz_base", "oil_jump_war", "oil_jump_hormuz",
              "me_war_deesc", "me_hz_persist", "oil_pass_infl", "oil_drag_growth"}

def transfer_theta(trained: np.ndarray, lam_weak=0.30) -> np.ndarray:
    fwd = THETA_DEFAULT.copy().astype(float)
    for i, n in enumerate(THETA_NAMES):
        fwd[i] = trained[i] if n in IDENTIFIED else \
                 (1 - lam_weak) * THETA_DEFAULT[i] + lam_weak * trained[i]
    return clip_theta(fwd)


class CalibrationTrainer:
    """SPSA minimization of Brier(replay forecasts, resolved outcomes).

    events: optional [(name, outcome, extractor)] — e.g. registry-derived
    (Task 51, load_registry_events). Defaults to the hand-built replay set.
    replay_Q: simulation quarters needed to cover the event set's windows."""

    def __init__(self, n_paths=2500, seed=11, prior_reg=0.06,
                 events=None, replay_Q: int | None = None):
        self.n_paths, self.seed = n_paths, seed
        self.prior_reg = prior_reg          # L2 pull toward expert prior (default theta)
        self.events, self.replay_Q = events, replay_Q
        self.history: list[dict] = []

    def _probs(self, engine, seed):
        return replay_event_probs(engine, N=self.n_paths, seed=seed,
                                  events=self.events, Q=self.replay_Q)

    def loss(self, theta: np.ndarray, seed=None) -> float:
        eng = WorldEngine(theta=theta)
        preds, outs = self._probs(eng, self.seed if seed is None else seed)
        reg = self.prior_reg * float(np.mean((to_z(theta) - to_z(THETA_DEFAULT)) ** 2))
        return brier(preds, outs) + reg

    def train(self, iters=40, a0=0.30, c0=0.10, verbose=True) -> np.ndarray:
        z = to_z(THETA_DEFAULT.copy())
        rng = np.random.default_rng(99)
        best_z, best_L = z.copy(), self.loss(to_theta(z))
        for k in range(iters):
            ak = a0 / (1 + k) ** 0.602          # standard SPSA gain schedules
            ck = c0 / (1 + k) ** 0.101
            delta = rng.choice([-1.0, 1.0], size=z.shape)
            seed_k = 1000 + k                    # common random numbers both sides
            Lp = self.loss(to_theta(np.clip(z + ck * delta, 0, 1)), seed=seed_k)
            Lm = self.loss(to_theta(np.clip(z - ck * delta, 0, 1)), seed=seed_k)
            ghat = (Lp - Lm) / (2 * ck) * delta  # SPSA gradient estimate
            z = np.clip(z - ak * ghat, 0, 1)
            L = self.loss(to_theta(z), seed=7)   # fixed-seed eval for comparability
            self.history.append({"iter": k, "loss": round(L, 5),
                                 "loss_plus": round(Lp, 5), "loss_minus": round(Lm, 5)})
            if L < best_L:
                best_L, best_z = L, z.copy()
            if verbose and (k % 10 == 0 or k == iters - 1):
                print(f"  SPSA iter {k:3d}  loss={L:.5f}  best={best_L:.5f}")
        self.trained_theta = clip_theta(to_theta(best_z))
        self.best_loss = best_L
        return self.trained_theta

    def report(self) -> dict:
        base = WorldEngine(THETA_DEFAULT)
        trained = WorldEngine(self.trained_theta)
        pb, outs = self._probs(base, 7)
        pt, _ = self._probs(trained, 7)
        from core.engine import RESOLVED_EVENTS
        ev_set = self.events if self.events is not None else RESOLVED_EVENTS
        return {
            "brier_before": round(brier(pb, outs), 5),
            "brier_after": round(brier(pt, outs), 5),
            "log_before": round(log_score(pb, outs), 5),
            "log_after": round(log_score(pt, outs), 5),
            "events": [{"event": n, "outcome": int(o),
                        "p_before": round(float(b), 3), "p_after": round(float(a), 3)}
                       for (n, o, _), b, a in zip(ev_set, pb, pt)],
            "theta_before": {k: round(float(v), 5) for k, v in zip(THETA_NAMES, THETA_DEFAULT)},
            "theta_after": {k: round(float(v), 5) for k, v in zip(THETA_NAMES, self.trained_theta)},
            "history": self.history,
        }


class Adversary:
    """Min-max bands: extremize each forecast prob over ||z - z0|| <= rho."""

    def __init__(self, theta_center: np.ndarray, rho=0.10, n_probe=24,
                 n_paths=3000, Q=12, seed=5):
        self.z0 = to_z(theta_center)
        self.rho, self.n_probe, self.n_paths, self.Q, self.seed = rho, n_probe, n_paths, Q, seed

    def _probs(self, z, keys) -> dict:
        eng = WorldEngine(theta=to_theta(z))
        sim = eng.simulate(N=self.n_paths, Q=self.Q, seed=self.seed)  # CRN across probes
        ev = event_probs(sim)
        return {k: ev[k] for k in keys if ev.get(k) is not None}

    def bands(self, keys: list[str]) -> dict:
        rng = np.random.default_rng(17)
        center = self._probs(self.z0, keys)
        lo = {k: v for k, v in center.items()}; hi = {k: v for k, v in center.items()}
        worst_dir = {k: None for k in center}
        for i in range(self.n_probe):
            d = rng.normal(size=self.z0.shape)
            d *= self.rho / (np.linalg.norm(d) + EPS)
            for sgn in (1.0, -1.0):
                z = np.clip(self.z0 + sgn * d, 0, 1)
                pv = self._probs(z, keys)
                for k, v in pv.items():
                    if v < lo[k]: lo[k] = v
                    if v > hi[k]: hi[k], worst_dir[k] = v, np.round(sgn * d, 3).tolist()
        return {k: {"center": center[k], "lo": round(lo[k], 4), "hi": round(hi[k], 4)}
                for k in center}


class ConformalLayer:
    """Split-conformal widening from resolved-event residuals (heuristic floor).

    Nonconformity = CALIBRATION-EXCESS score, not raw |p - y|: a perfectly
    calibrated forecaster of a p-event still incurs E|p - y| = 2p(1-p), so raw
    residuals over-penalize honest mid-range probabilities. We score only the
    residual IN EXCESS of the perfectly calibrated expectation:
        s_i = max(0, |p_i - y_i| - 2 p_i (1 - p_i))
    and widen bands by the 80% quantile of s."""

    def __init__(self, engine: WorldEngine, n_paths=3000):
        preds, outs = replay_event_probs(engine, N=n_paths, seed=23)
        raw = np.abs(preds - outs)
        ideal = 2.0 * preds * (1.0 - preds)              # E|p-y| under calibration
        self.residuals = np.maximum(0.0, raw - ideal)    # calibration-excess scores
        n = len(self.residuals)
        qlev = min(1.0, np.ceil((n + 1) * 0.8) / n)      # 80% target
        self.q80 = float(np.quantile(self.residuals, qlev))

    def widen(self, band: dict) -> dict:
        return {"lo": round(max(0.0, band["lo"] - self.q80), 4),
                "hi": round(min(1.0, band["hi"] + self.q80), 4),
                "center": band["center"], "conformal_q80": round(self.q80, 4)}


# ---------------------------------------------------------------------------
# Task 51 — registry-derived training events
# ---------------------------------------------------------------------------
# Maps RESOLVED registry questions onto simulator observables so the trainer
# learns from REAL outcomes instead of the 10 hand-built replay events.
# v1 mapping: series_threshold rules on 'brent_usd' -> oil-path extractors.
# Approximation (documented): the replay simulator is QUARTERLY from 2026Q1;
# daily question windows map to the quarters they overlap.

def _qidx(date_str: str) -> int:
    """Quarter index relative to the 2026Q1 replay start."""
    from datetime import datetime
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d.year - 2026) * 4 + (d.month - 1) // 3

_SERIES_OPS = {">": lambda a, v: a > v, ">=": lambda a, v: a >= v,
               "<": lambda a, v: a < v, "<=": lambda a, v: a <= v}

def _make_oil_extractor(op: str, value: float, qa: int, qb: int):
    cmp = _SERIES_OPS[op]
    def extract(sim):
        return cmp(sim["oil"][:, qa:qb + 1], value).any(axis=1)
    return extract

def load_registry_events(reg, max_Q: int = 8) -> tuple[list, list, int]:
    """-> (events, meta, required_Q).
    events: [(name, outcome, extractor)] for CalibrationTrainer;
    meta:   [{key, asof, by}] aligned with events (for rolling-origin splits);
    required_Q: replay quarters needed to cover all windows."""
    import json as _json
    events, meta, req_q = [], [], 2
    for q in reg.list(resolved=True):
        rule = q.get("resolution_rule")
        rule = _json.loads(rule) if isinstance(rule, str) else (rule or {})
        if rule.get("type") != "series_threshold" or rule.get("series") != "brent_usd":
            continue
        if q.get("outcome") is None or not rule.get("from") or not rule.get("by"):
            continue
        qa, qb = max(0, _qidx(rule["from"])), _qidx(rule["by"])
        if qb < qa or qb >= max_Q:
            continue
        events.append((q["key"], int(q["outcome"]),
                       _make_oil_extractor(rule["op"], float(rule["value"]), qa, qb)))
        meta.append({"key": q["key"], "asof": rule["from"], "by": rule["by"]})
        req_q = max(req_q, qb + 1)
    return events, meta, req_q

def rolling_split(events: list, meta: list, split_date: str) -> tuple[list, list]:
    """Rolling-origin: train on questions resolving by split_date, eval after."""
    train, evl = [], []
    for ev, m in zip(events, meta):
        (train if m["by"] <= split_date else evl).append(ev)
    return train, evl


# ---------------------------------------------------------------------------
# (4) Intervention engine
# ---------------------------------------------------------------------------
INTERVENTIONS = [
    # name, hazard channel mods, annualized cost (index units), description
    ("Gulf maritime verification coalition", {"me_esc": 0.80, "me_hz": 0.60}, 3.0,
     "Sensors, escorts, deconfliction hotline; cuts escalation and closure hazards"),
    ("Strategic energy buffer package",      {"me_hz": 0.85},                2.5,
     "Coordinated SPR rules + LNG/grid interconnects; halves price spike persistence"),
    ("EM bridge-financing window",           {"em_haz": 0.65},               2.0,
     "Pre-arranged IMF+regional facility ahead of 2027 maturities"),
    ("Ukraine armistice technical track",    {"ua_cf": 1.35},                1.0,
     "Monitoring tech and DMZ design ready before politics ripen"),
    ("LIC food-security facility",           {"food_shock": 0.70, "em_haz": 0.90}, 1.5,
     "Targeted imports financing pre-El Nino"),
    ("Taiwan deterrence-by-denial",          {"tw_block": 0.80},             4.0,
     "Munitions, hardening, allied drills without symbolic provocation"),
    ("AI-security compact",                  {"em_haz": 0.95, "me_esc": 0.97}, 1.2,
     "Provenance + infrastructure red-lines; small systemic-hazard trim (proxy)"),
]

def harm_functional(sim: dict, w_rec=1.0, w_war=1.0, w_def=0.6, w_infl=0.5) -> float:
    """Expected harm index over the ensemble (lower is better)."""
    g, pi, me, tw = sim["growth"], sim["inflation"], sim["me"], sim["tw"]
    rec_q = float(np.mean((g < 2.5).sum(1)))            # expected recession-quarters
    war_q = float(np.mean(((me >= 2).sum(1) + 4 * (tw == 2).sum(1))))
    defs = float(np.mean(sim["em_def"]))
    infl = float(np.mean(np.maximum(pi - 4, 0).sum(1)))
    return w_rec * rec_q + w_war * war_q + w_def * defs + w_infl * infl

class InterventionSearch:
    def __init__(self, theta, budget=8.0, n_paths=4000, Q=12, seed=31):
        self.eng = WorldEngine(theta=theta)
        self.budget, self.n_paths, self.Q, self.seed = budget, n_paths, Q, seed
        self.base_sim = self.eng.simulate(N=n_paths, Q=Q, seed=seed)
        self.base_harm = harm_functional(self.base_sim)

    def _harm(self, mods: dict) -> float:
        return harm_functional(self.eng.simulate(N=self.n_paths, Q=self.Q,
                                                 hazard_mods=mods, seed=self.seed))

    @staticmethod
    def _merge(sel: list) -> dict:
        mods = {}
        for _, m, _, _ in sel:
            for k, v in m.items():
                mods[k] = mods.get(k, 1.0) * v
        return mods

    def greedy(self) -> dict:
        remaining = list(INTERVENTIONS); selected = []; spent = 0.0
        cur_harm = self.base_harm; steps = []
        singles = []
        for iv in list(remaining):
            h = self._harm(self._merge([iv]))
            singles.append({"name": iv[0], "cost": iv[2],
                            "harm_reduction": round(self.base_harm - h, 3),
                            "value_per_cost": round((self.base_harm - h) / iv[2], 3),
                            "desc": iv[3]})
        while True:
            best, best_gain_pc, best_h = None, 0.0, None
            for iv in remaining:
                if spent + iv[2] > self.budget: continue
                h = self._harm(self._merge(selected + [iv]))
                gain_pc = (cur_harm - h) / iv[2]
                if gain_pc > best_gain_pc:
                    best, best_gain_pc, best_h = iv, gain_pc, h
            if best is None: break
            selected.append(best); remaining.remove(best); spent += best[2]
            steps.append({"added": best[0], "cost": best[2],
                          "portfolio_harm": round(best_h, 3),
                          "marginal_value_per_cost": round(best_gain_pc, 3)})
            cur_harm = best_h
        return {"base_harm": round(self.base_harm, 3),
                "portfolio": [s[0] for s in selected],
                "portfolio_harm": round(cur_harm, 3),
                "harm_reduction_pct": round(100 * (1 - cur_harm / self.base_harm), 1),
                "budget": self.budget, "spent": spent,
                "greedy_steps": steps, "singles_ranked":
                    sorted(singles, key=lambda d: -d["value_per_cost"])}
