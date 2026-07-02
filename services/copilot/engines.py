"""ARGUS Copilot — engine adapter over cassandra-core.
Startup: train/load theta, run cached baseline ensemble + bands.
Runtime: serve forecasts from cache; counterfactual/policy on demand (CRN-paired).
All numbers originate HERE (never from any LLM)."""
from __future__ import annotations
import os, sys, json, time, hashlib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

import numpy as np
from core.engine import WorldEngine, THETA_NAMES, event_probs
from core.phases import load_situation, ScenarioEngine, explain_forecast, red_team_summary
from novelty.cassandra import (CalibrationTrainer, Adversary, ConformalLayer,
                               InterventionSearch, transfer_theta, harm_functional,
                               INTERVENTIONS as IV_LIB)

from services.copilot.config import get_settings

SEED = 42  # default; Engines uses settings.seed (kept for backward import compat)

QUESTION_TEXT = {
    "ME_war_1y": "Middle East ceasefire breaks back into open war within 12 months",
    "ME_war_180d": "Middle East war re-ignition within 180 days",
    "ME_war_3y": "Middle East war re-ignition within 3 years",
    "Hormuz_closure_by_end2027": "Second closure of the Strait of Hormuz by end-2027",
    "ME_durable_settlement_3y": "Durable Middle East settlement within 3 years",
    "UA_ceasefire_by_end2026": "Russia-Ukraine ceasefire by end-2026",
    "UA_formal_ceasefire_by_end2027": "Formal Russia-Ukraine ceasefire by end-2027",
    "TW_blockade_by_2030": "PRC blockade/quarantine of Taiwan by 2030",
    "TW_blockade_by_2033": "PRC blockade/quarantine of Taiwan by 2033",
    "TW_conflict_by_2036": "PRC-Taiwan armed conflict by 2036",
    "Brent_gt120_1y": "Brent crude above $120 within 12 months",
    "Brent_gt150_2y": "Brent crude above $150 within 24 months",
    "Global_recession_lt2p5_by_2028": "Global annual growth below 2.5% in 2027 or 2028",
    "Inflation_gt5_2027avg": "Global inflation above 5% on average in 2027",
    "EM_default_quarters_ge3_by_2028": "Three or more EM default quarters by 2028",
    "Dem_House_Nov2026": "Democrats win the US House in November 2026",
}
HORIZON = {k: ("12m" if "1y" in k or "2026" in k else "6m" if "180d" in k else
               "to 2027" if "2027" in k else "to 2028" if "2028" in k else
               "to 2030" if "2030" in k else "to 2033" if "2033" in k else
               "to 2036" if "2036" in k else "3y" if "3y" in k else "2y")
           for k in QUESTION_TEXT}
BAND_KEYS = ["ME_war_1y", "Hormuz_closure_by_end2027", "UA_formal_ceasefire_by_end2027",
             "Brent_gt120_1y", "Global_recession_lt2p5_by_2028", "Inflation_gt5_2027avg"]

def _manifest(kind: str, payload: dict, theta) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"kind": kind, "theta": list(np.round(theta, 6)),
                         "seed": SEED, "payload": payload}, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]

def compute_bands(theta, eng, n_probe: int, n_paths: int, rho: float = 0.10, Q: int = 12) -> dict:
    """Adversary (plausibility-ball) + conformal robust bands for the headline keys."""
    raw = Adversary(theta, rho=rho, n_probe=n_probe, n_paths=n_paths, Q=Q).bands(BAND_KEYS)
    conf = ConformalLayer(eng, n_paths=n_paths)
    return {k: conf.widen(b) for k, b in raw.items()}


class Engines:
    """Singleton holding trained theta + cached baseline artifacts."""

    def __init__(self, fast: bool | None = None):
        t0 = time.time()
        cfg = get_settings()
        fast = cfg.fast if fast is None else fast
        self.seed = cfg.seed
        global SEED
        SEED = cfg.seed
        self.theta_cache = cfg.theta_cache
        self.situation = load_situation()
        theta = self._load_or_train(fast)
        from services.kg.gate import gate_theta          # Task 57: id-status gate
        self.theta, self.gate_report = gate_theta(theta)
        self.theta_hash = hashlib.sha256(np.round(self.theta, 6).tobytes()).hexdigest()[:12]
        self.eng = WorldEngine(theta=self.theta, seed=SEED)
        # cached baseline ensemble (forward forecasts); optionally sharded across
        # parallel region slices (Task 82) when ARGUS_ENGINE_SHARDS > 1.
        N = 4000 if fast else 20000
        self.shard_report = None
        if cfg.engine_shards > 1:
            from services.copilot.sharding import sharded_simulate, DEFAULT_REGIONS
            shards = cfg.engine_shards
            names = DEFAULT_REGIONS[:shards] if shards <= len(DEFAULT_REGIONS) else None
            res = sharded_simulate(self.theta, N, 40, SEED, shards=shards, region_names=names)
            self.base_sim, self.shard_report = res["sim"], res["shards"]
        else:
            self.base_sim = self.eng.simulate(N=N, Q=40, seed=SEED)
        self.events = event_probs(self.base_sim)
        self.scenarios = ScenarioEngine(self.base_sim).cluster(k=4)
        # robust bands: prefer the nightly full-fidelity cache for this theta (Task 83)
        self.bands, self.bands_source = self._load_or_compute_bands(fast)
        self.redteam = red_team_summary(self.bands, self.situation)
        self.fans = self._fans()
        self.startup_s = round(time.time() - t0, 1)

    def _load_or_train(self, fast: bool):
        # 1) promoted champion from the theta-versions registry (Task 53)
        try:
            from services.copilot.store import get_store
            row = get_store().theta_promoted()
            if row and list(row["names"]) == THETA_NAMES:
                self.theta_source = "promoted-db"
                return np.array([float(v) for v in row["vals"]])
        except Exception:
            pass
        # 2) file cache
        if os.path.exists(self.theta_cache):
            with open(self.theta_cache) as f:
                d = json.load(f)
            if d.get("names") == THETA_NAMES:
                self.theta_source = "file-cache"
                return np.array(d["theta"])
        # 3) train fresh; record as version (bootstrap-promote if none exists)
        tr = CalibrationTrainer(n_paths=1200 if fast else 2500)
        trained = tr.train(iters=12 if fast else 40, verbose=False)
        theta = transfer_theta(trained)
        os.makedirs(os.path.dirname(self.theta_cache), exist_ok=True)
        with open(self.theta_cache, "w") as f:
            json.dump({"names": THETA_NAMES, "theta": [float(x) for x in theta],
                       "brier_after": tr.best_loss}, f)
        self.theta_source = "trained"
        try:
            from services.copilot.store import get_store
            import hashlib as _h
            th = _h.sha256(np.round(theta, 6).tobytes()).hexdigest()[:12]
            st = get_store()
            st.theta_save(th, THETA_NAMES, [float(x) for x in theta],
                          tr.best_loss, "startup bootstrap")
            if st.theta_promoted() is None:
                st.theta_promote(th)
                self.theta_source = "trained+promoted"
        except Exception:
            pass
        return theta

    def _load_or_compute_bands(self, fast: bool):
        """Task 83: serve the nightly full-fidelity bands for this theta if cached
        (so a fast-startup API still shows full-fidelity bands); else compute."""
        try:
            from services.copilot.store import get_store
            cached = get_store().bands_get(self.theta_hash)
            if cached and all(k in cached["bands"] for k in BAND_KEYS):
                return cached["bands"], f"cache:{cached.get('fidelity', '?')}"
        except Exception:
            pass
        n_probe, n_paths = (6, 1200) if fast else (20, 3000)
        bands = compute_bands(self.theta, self.eng, n_probe, n_paths)
        return bands, ("computed-fast" if fast else "computed-full")

    def _fans(self):
        out = {}
        yrs = list(range(2027, 2037))
        for var in ["oil", "growth", "inflation"]:
            a = self.base_sim[var]
            q = {p: [float(x) for x in np.round(np.percentile(a, p, axis=0)[3::4], 2)]
                 for p in [10, 25, 50, 75, 90]}
            out[var] = {"variable": var, "years": yrs, "p10": q[10], "p25": q[25],
                        "p50": q[50], "p75": q[75], "p90": q[90]}
        return out

    # ---------- read APIs ----------
    def forecast(self, key: str) -> dict | None:
        p = self.events.get(key)
        if p is None:
            return None
        b = self.bands.get(key)
        verdict = None
        for f in self.redteam["findings"]:
            if f["forecast"] == key:
                verdict = f["verdict"].split(" — ")[0]
        return {"key": key, "question_text": QUESTION_TEXT.get(key, key),
                "probability": p,
                "band": ({"lo": b["lo"], "hi": b["hi"], "conformal_q80": b["conformal_q80"]} if b else None),
                "verdict": verdict, "horizon": HORIZON.get(key),
                "confidence": ("moderate" if b and (b["hi"] - b["lo"]) < 0.25 else
                               "low-moderate" if b else "model-only"),
                "manifest_id": _manifest("forecast", {"key": key}, self.theta)}

    def all_forecasts(self) -> list[dict]:
        return [self.forecast(k) for k in QUESTION_TEXT if self.events.get(k) is not None]

    def explanation(self, key: str) -> dict | None:
        if key not in self.situation["explanations"]:
            return None
        e = explain_forecast(key, self.events.get(key), self.situation, self.theta)
        return e

    def analogs(self, query: str = "") -> list[dict]:
        al = self.situation["analogs"]
        if not query:
            return al
        q = query.lower()
        scored = sorted(al, key=lambda a: -sum(w in (a["name"] + a["similar"]).lower()
                                               for w in q.split()))
        return scored

    def ewi(self) -> list[dict]:
        return self.situation["early_warning"]

    def facts(self) -> list[dict]:
        return self.situation["facts"]

    # ---------- compute APIs ----------
    def counterfactual(self, interventions: list[str], hazard_mods: dict[str, float],
                       targets: list[str], horizon_q: int = 12, n_paths: int = 2000) -> dict:
        from services.copilot.cfcache import get_cf_cache, clause_key   # Task 85
        cache = get_cf_cache()
        ckey = clause_key(interventions, hazard_mods, targets, horizon_q, n_paths, self.theta_hash)
        hit = cache.get(ckey)
        if hit is not None:
            return hit
        mods = dict(hazard_mods)
        names = []
        for iv in IV_LIB:
            if iv[0] in interventions:
                names.append(iv[0])
                for k, v in iv[1].items():
                    mods[k] = mods.get(k, 1.0) * v
        base = self.eng.simulate(N=n_paths, Q=horizon_q, seed=SEED)          # CRN pair
        cf = self.eng.simulate(N=n_paths, Q=horizon_q, hazard_mods=mods, seed=SEED)
        eb, ec = event_probs(base), event_probs(cf)
        effects = []
        for tkey in targets:
            if eb.get(tkey) is None:
                continue
            d = ec[tkey] - eb[tkey]
            effects.append({"target": tkey, "baseline": eb[tkey], "counterfactual": ec[tkey],
                            "delta": round(d, 4),
                            "rel_change_pct": round(100 * d / max(eb[tkey], 1e-9), 1)})
        payload = {"interventions": names, "mods": mods, "targets": targets, "Q": horizon_q}
        result = {"effects": effects,
                  "harm_baseline": round(harm_functional(base), 3),
                  "harm_counterfactual": round(harm_functional(cf), 3),
                  "assumptions": [
                      "Interventional (do-operator) semantics on hazard channels; paired common-random-number paths",
                      f"Trained-transferred theta ({self.theta_hash}); mechanism id-status: mixed (see blueprint §5)",
                      "Effects are ensemble probability shifts, not guarantees"],
                  "manifest_id": _manifest("counterfactual", payload, self.theta)}
        cache.set(ckey, result)
        return result

    def counterfactual_chunked(self, interventions: list[str], hazard_mods: dict[str, float],
                               targets: list[str], horizon_q: int = 12,
                               n_paths: int = 20000, n_batches: int = 5,
                               progress_cb=None) -> dict:
        """Task 62: large counterfactual split into CRN path-batches so callers
        can stream REAL progress. Per batch: paired base/cf sims on a distinct
        seed; event probabilities aggregate as equal-weight batch means."""
        from novelty.cassandra import harm_functional, INTERVENTIONS as IV_LIB
        mods = dict(hazard_mods)
        names = []
        for iv in IV_LIB:
            if iv[0] in interventions:
                names.append(iv[0])
                for k, v in iv[1].items():
                    mods[k] = mods.get(k, 1.0) * v
        per = max(200, n_paths // n_batches)
        sums_b: dict[str, float] = {}; sums_c: dict[str, float] = {}
        harm_b = harm_c = 0.0
        for i in range(n_batches):
            seed = self.seed + 1000 + i
            base = self.eng.simulate(N=per, Q=horizon_q, seed=seed)
            cf = self.eng.simulate(N=per, Q=horizon_q, hazard_mods=mods, seed=seed)
            eb, ec = event_probs(base), event_probs(cf)
            for t in targets:
                if eb.get(t) is None:
                    continue
                sums_b[t] = sums_b.get(t, 0.0) + eb[t]
                sums_c[t] = sums_c.get(t, 0.0) + ec[t]
            harm_b += harm_functional(base); harm_c += harm_functional(cf)
            if progress_cb:
                progress_cb(i + 1, n_batches)
        effects = []
        for t in targets:
            if t not in sums_b:
                continue
            pb, pc = sums_b[t] / n_batches, sums_c[t] / n_batches
            effects.append({"target": t, "baseline": round(pb, 4),
                            "counterfactual": round(pc, 4),
                            "delta": round(pc - pb, 4),
                            "rel_change_pct": round(100 * (pc - pb) / max(pb, 1e-9), 1)})
        payload = {"interventions": names, "mods": mods, "targets": targets,
                   "Q": horizon_q, "n_paths": per * n_batches, "batches": n_batches}
        return {"effects": effects,
                "harm_baseline": round(harm_b / n_batches, 3),
                "harm_counterfactual": round(harm_c / n_batches, 3),
                "assumptions": ["chunked CRN batches (equal-weight aggregation)",
                                f"trained-transferred theta ({self.theta_hash})"],
                "n_paths_total": per * n_batches,
                "manifest_id": _manifest("counterfactual-chunked", payload, self.theta)}

    def policy(self, budget: float = 8.0, n_paths: int = 1500) -> dict:
        s = InterventionSearch(self.theta, budget=budget, n_paths=n_paths, Q=12, seed=31)
        res = s.greedy()
        res["caveats"] = [
            "Harm functional weights are value judgments (visible, versioned)",
            "Costs are index units; calibrate to fiscal units before real studies",
            "Recommendation sign verified under adversarial theta ball in full pipeline runs"]
        res["manifest_id"] = _manifest("policy", {"budget": budget}, self.theta)
        return res

ENGINES: Engines | None = None

def get_engines() -> Engines:
    global ENGINES
    if ENGINES is None:
        ENGINES = Engines()          # fast/seed/theta_cache from config.get_settings()
    return ENGINES
