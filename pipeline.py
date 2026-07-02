"""
CASSANDRA Core — 12-Phase Pipeline Orchestrator
Run:  python pipeline.py [--fast]
Out:  output/report.json, output/charts/*.png, output/dashboard.html
"""
from __future__ import annotations
import json, os, sys, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.engine import (WorldEngine, THETA_DEFAULT, THETA_NAMES, event_probs,
                         theta_dict, RESOLVED_EVENTS)
from core.phases import load_situation, CausalGraph, ScenarioEngine, explain_forecast, red_team_summary
from novelty.cassandra import (CalibrationTrainer, Adversary, ConformalLayer,
                               InterventionSearch, brier, transfer_theta, IDENTIFIED)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
CHARTS = os.path.join(OUT, "charts")

BAND_KEYS = ["ME_war_1y", "Hormuz_closure_by_end2027", "UA_formal_ceasefire_by_end2027",
             "Brent_gt120_1y", "Global_recession_lt2p5_by_2028", "Inflation_gt5_2027avg"]

EXPLAIN_KEYS = ["ME_war_1y", "Hormuz_closure_by_end2027", "UA_formal_ceasefire_by_end2027",
                "TW_blockade_by_2030", "Global_recession_lt2p5_by_2028", "Dem_House_Nov2026"]

def run(fast=False):
    os.makedirs(CHARTS, exist_ok=True)
    t0 = time.time()
    situation = load_situation()
    report = {"meta": {"system": "CASSANDRA Core v1.0",
                       "as_of": situation["as_of"],
                       "pipeline": "12-phase strategic forecasting",
                       "fast_mode": fast}}

    # ---- Phase 1-2: situation + signals (data-driven) ----------------------
    report["phase1_situation"] = situation["facts"]
    report["phase2_signals"] = situation["signals"]
    print(f"[1-2] situation+signals loaded ({len(situation['facts'])} facts)")

    # ---- NOVELTY (1): calibration-train theta on resolved events -----------
    trainer = CalibrationTrainer(n_paths=1200 if fast else 2500)
    theta_trained = trainer.train(iters=12 if fast else 40, verbose=True)
    calib = trainer.report()
    theta = transfer_theta(theta_trained)            # identifiability-aware deployment theta
    calib["transfer"] = {
        "identified_params_kept": sorted(IDENTIFIED),
        "weak_params_shrunk_lambda": 0.30,
        "theta_deployed": {k: round(float(v), 5) for k, v in zip(THETA_NAMES, theta)},
        "note": "Replay window starts in active war: war-state mechanics are identified "
                "and kept; ceasefire-state hazards are weakly identified and shrunk toward "
                "the expert prior to avoid escalation-selection bias in forward forecasts."}
    report["novelty_calibration"] = calib
    print(f"[N1] calibration: Brier {calib['brier_before']} -> {calib['brier_after']}; "
          f"deployed theta = identifiability-aware transfer  ({time.time()-t0:.0f}s)")

    # ---- Phase 3: causal graph (priors + perturbation-verified weights) ----
    cg = CausalGraph(situation)
    report["phase3_causal"] = {
        "expert_prior_weights_pct": situation["expert_prior_weights"],
        "perturbation_verified_weights_pct":
            cg.empirical_weights(theta, n_paths=1200 if fast else 2500),
        "edges": situation["causal_edges"],
        "note": "Prior weights are judgment; verified weights = share of harm-functional "
                "sensitivity under +/-20% channel perturbation in the trained simulator."}
    print(f"[3] causal weights verified ({time.time()-t0:.0f}s)")

    # ---- Phase 4: analogs ---------------------------------------------------
    report["phase4_analogs"] = situation["analogs"]

    # ---- Phase 5-7: system dynamics + agents + ensemble forecasts ----------
    eng = WorldEngine(theta=theta)
    sim = eng.simulate(N=6000 if fast else 20000, Q=40, seed=42)
    ev = event_probs(sim)
    fans = {}
    for key, label in [("oil", "Brent $/bbl"), ("growth", "Global growth %"), ("inflation", "Global inflation %")]:
        a = sim[key]
        fans[key] = {str(p): [float(x) for x in np.round(np.percentile(a, p, axis=0)[3::4], 2)]
                     for p in [10, 25, 50, 75, 90]}
    report["phase5_7_forecasts"] = {
        "event_probabilities": ev,
        "fans_annual_2027_2036": fans,
        "mc_se_95": round(1.96 * float(np.sqrt(0.25 / sim["N"])), 4),
        "calibration_2026H2": {"growth_mean": round(float(sim["growth"][:, :2].mean()), 2),
                               "inflation_mean": round(float(sim["inflation"][:, :2].mean()), 2),
                               "oil_mean": round(float(sim["oil"][:, :2].mean()), 1),
                               "anchors": {"imf_growth": 3.1, "imf_inflation": 4.4, "brent_spot": 94.0}}}
    print(f"[5-7] ensemble {sim['N']} paths x {sim['Q']}q  ({time.time()-t0:.0f}s)")

    # ---- Phase 8: scenarios (discovered by clustering) ----------------------
    report["phase8_scenarios"] = ScenarioEngine(sim).cluster(k=4)
    print(f"[8] scenarios clustered ({time.time()-t0:.0f}s)")

    # ---- NOVELTY (2)+(3): adversarial bands + conformal widening ------------
    adv = Adversary(theta, rho=0.10, n_probe=8 if fast else 20,
                    n_paths=1500 if fast else 3000, Q=12)
    bands = adv.bands(BAND_KEYS)
    conf = ConformalLayer(eng, n_paths=1500 if fast else 3000)
    robust = {k: conf.widen(b) for k, b in bands.items()}
    report["novelty_adversarial_bands"] = bands
    report["novelty_robust_bands"] = robust
    print(f"[N2-3] adversarial+conformal bands ({time.time()-t0:.0f}s)")

    # ---- Phase 9: explainable forecasts -------------------------------------
    report["phase9_explanations"] = [
        explain_forecast(k, ev.get(k), situation, theta) for k in EXPLAIN_KEYS]

    # ---- NOVELTY (4) / Phase 10: intervention search ------------------------
    isearch = InterventionSearch(theta, budget=8.0,
                                 n_paths=1500 if fast else 4000, Q=12)
    report["phase10_policy"] = isearch.greedy()
    print(f"[10] intervention portfolio ({time.time()-t0:.0f}s)")

    # ---- Phase 11: early warning + unknowns ----------------------------------
    report["phase11_early_warning"] = situation["early_warning"]
    report["phase11_critical_unknowns"] = situation["critical_unknowns"]

    # ---- Phase 12: red team (graded on the ROBUST bands) -----------------------
    report["phase12_red_team"] = red_team_summary(robust, situation)

    # ---- charts ---------------------------------------------------------------
    make_charts(sim, ev, calib, report)
    print(f"[charts] written ({time.time()-t0:.0f}s)")

    # ---- save -----------------------------------------------------------------
    with open(os.path.join(OUT, "report.json"), "w") as f:
        json.dump(report, f, indent=1, default=float)
    make_dashboard(report)
    print(f"DONE in {time.time()-t0:.0f}s -> output/report.json, output/dashboard.html")
    return report


def make_charts(sim, ev, calib, report):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    yrs = np.arange(2027, 2037)
    # fan charts
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    for ax, (key, ttl, unit) in zip(axes, [("oil", "Brent crude", "$/bbl"),
                                           ("growth", "Global GDP growth", "%"),
                                           ("inflation", "Global inflation", "%")]):
        a = sim[key]
        f10, f25, f50, f75, f90 = [np.percentile(a, p, axis=0)[3::4] for p in [10, 25, 50, 75, 90]]
        ax.fill_between(yrs, f10, f90, alpha=0.18, color="#1f4e79")
        ax.fill_between(yrs, f25, f75, alpha=0.35, color="#1f4e79")
        ax.plot(yrs, f50, color="#0b2b4c", lw=2)
        ax.set_title(ttl, fontsize=11); ax.set_ylabel(unit); ax.grid(alpha=0.3)
    fig.suptitle("CASSANDRA ensemble fans (calibration-trained theta)", fontsize=12)
    fig.tight_layout(); fig.savefig(os.path.join(CHARTS, "fans.png"), dpi=150); plt.close(fig)
    # event probabilities with robust bands
    rb = report["novelty_robust_bands"]
    keys = [k for k in rb]
    fig2, ax = plt.subplots(figsize=(8.5, 4.2))
    ys = range(len(keys))
    ax.barh(list(ys), [rb[k]["center"] * 100 for k in keys], color="#1f4e79", alpha=0.85)
    for i, k in enumerate(keys):
        ax.plot([rb[k]["lo"] * 100, rb[k]["hi"] * 100], [i, i], color="#c00000", lw=2.5)
        ax.text(rb[k]["hi"] * 100 + 1, i, f"{rb[k]['center']*100:.0f}% [{rb[k]['lo']*100:.0f}-{rb[k]['hi']*100:.0f}]",
                va="center", fontsize=8)
    ax.set_yticks(list(ys)); ax.set_yticklabels(keys, fontsize=8); ax.invert_yaxis()
    ax.set_xlabel("probability (%) — bar = center, red = adversarial-conformal band")
    ax.set_title("Forecasts with adversarially robust bands", fontsize=11)
    ax.grid(axis="x", alpha=0.3); fig2.tight_layout()
    fig2.savefig(os.path.join(CHARTS, "robust_bands.png"), dpi=150); plt.close(fig2)
    # calibration before/after
    evs = calib["events"]
    fig3, ax = plt.subplots(figsize=(8.5, 4.2))
    x = np.arange(len(evs))
    ax.bar(x - 0.2, [e["p_before"] for e in evs], width=0.4, label="before training", color="#9dc3e6")
    ax.bar(x + 0.2, [e["p_after"] for e in evs], width=0.4, label="after training", color="#1f4e79")
    ax.scatter(x, [e["outcome"] for e in evs], color="#c00000", zorder=5, label="outcome", s=40)
    ax.set_xticks(x); ax.set_xticklabels([e["event"][:18] for e in evs], rotation=35, ha="right", fontsize=7)
    ax.set_ylabel("probability"); ax.legend(fontsize=8)
    ax.set_title(f"Novelty 1 — calibration training on resolved events "
                 f"(Brier {calib['brier_before']} → {calib['brier_after']})", fontsize=10)
    fig3.tight_layout(); fig3.savefig(os.path.join(CHARTS, "calibration.png"), dpi=150); plt.close(fig3)


def make_dashboard(report):
    tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_template.html")
    with open(tpl_path) as f:
        tpl = f.read()
    html = tpl.replace("/*__REPORT_JSON__*/null", json.dumps(report, default=float))
    with open(os.path.join(OUT, "dashboard.html"), "w") as f:
        f.write(html)


if __name__ == "__main__":
    run(fast="--fast" in sys.argv)
