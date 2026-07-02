# CASSANDRA Core

**Calibration-Adversarial, Simulation-Supervised Architecture for Networked Dynamics & Risk Analysis**

A working implementation of a National Strategic Intelligence and Societal Forecasting Core: a 12-phase analytic pipeline that ingests a structured world situation, runs a calibration-trained Monte Carlo world model with strategic-actor agents, and emits probabilistic forecasts with adversarially robust uncertainty bands, discovered scenarios, ranked policy interventions, early-warning indicators, and a built-in red team — every forecast carrying its own evidence chain.

Evidence baseline: **11 June 2026** (post-Iran-war world: fragile Gulf ceasefire, Brent ~$94, IMF 3.1%/4.4% reference).

---

## Quickstart

```bash
pip install -r requirements.txt -r requirements-api.txt
python pipeline.py                   # full 12-phase batch run (~3s) -> output/
python tests/test_smoke.py           # 14 engine tests
python -m pytest tests/test_api.py -q  # 12 copilot API tests
python benchmarks/bench_api.py       # SLO gate (all PASS)

# the conversational copilot:
uvicorn services.copilot.main:app --port 8000
open http://localhost:8000/          # chat UI — ask in natural language
```

## Conversational copilot (`services/copilot/`)

A working FastAPI intelligence copilot over the engines: closed-grammar NLU (10 intents — forecast, why/cause, what-if, policy, early-warning, vulnerability, analogs, scenarios, status; optional Ollama assist for parsing only), grounded answer composer (numbers come exclusively from scored engines; off-grammar questions abstain), paired-CRN counterfactuals, budgeted policy search, session memory, and a reproducibility manifest + audit endpoint on every answer. 16 REST endpoints (`/docs` for OpenAPI). Measured: read p95 <1 ms, what-if p95 ~29 ms, policy p95 ~205 ms.

Deployment artifacts: `db/` (PostgreSQL DDL, Neo4j TCKG schema, Kafka topics), `deploy/` (Dockerfile, docker-compose with phase2/llm profiles, Kubernetes manifests with HPA + nightly pipeline CronJob), `.github/workflows/ci.yml` (tests → SLO gate → container smoke). Execution roadmap: **`docs/BUILD_PLAN.md`** — phases 1–4, solo day-by-day and 5-person week-by-week plans, and the first 100 tasks (38 complete in this repo).

CLI:

```bash
python cli.py run [--fast]   # full pipeline
python cli.py train          # calibration training only
python cli.py redteam ME_war_1y Hormuz_closure_by_end2027
python cli.py intervene      # policy portfolio search
python cli.py forecast       # quick ensemble probabilities
```

---

## Architecture

```
data/situation.json ──► Phases 1-2  facts + scored signals
        │
        ▼
┌─ core/engine.py ─────────────────────────────────────────────┐
│ WorldEngine(θ): regime-switching system dynamics              │
│   ME{settled,ceasefire,war,Hormuz} × UA{frozen,low,war}       │
│   × TW{quo,blockade,conflict} + oil/growth/inflation/food/EM  │
│ Strategic-actor layer (Phase 6): Iran/US/Russia/PRC softmax   │
│   stances modulate hazards each quarter (endogenous escalation)│
│ Replay mode: re-init at Feb-2026 for leakage-firewalled eval  │
└──────────────┬────────────────────────────────────────────────┘
               ▼
┌─ novelty/cassandra.py — THE RESEARCH LAYER ──────────────────┐
│ N1 CalibrationTrainer  SPSA trains θ end-to-end on Brier vs   │
│                        resolved events (proper-scoring-rule    │
│                        supervision of causal mechanism params) │
│ N2 Adversary           min-max bands over plausibility ball   │
│ N3 ConformalLayer      conformal widening of adversarial bands│
│ N4 InterventionSearch  greedy EV portfolio over do-operations │
└──────────────┬────────────────────────────────────────────────┘
               ▼
pipeline.py  Phases 1-12 ──► output/report.json
                          ──► output/charts/*.png
                          ──► output/dashboard.html (8 tabs)
```

### Phase map

| Phase | Spec requirement | Where |
|---|---|---|
| 1 | Situation awareness | `data/situation.json` facts (14 sourced) |
| 2 | Signal extraction (strength/reliability/growth/horizon/impact) | `situation.json` signals + dashboard |
| 3 | Causal reasoning, weighted map | `core/phases.py` `CausalGraph` — priors **verified by simulator perturbation** |
| 4 | Historical analog engine | `situation.json` analogs (similarity/lessons/policy success+failure) |
| 5 | System dynamics (loops, tipping points) | `core/engine.py` coupled dynamics |
| 6 | Agent-based simulation | `actor_stances()` — bounded-rational strategic actors |
| 7 | Forecast generation (7d→10y) | `event_probs()` + fans, 20k paths × 40 quarters |
| 8 | Four scenarios | `ScenarioEngine` — **discovered by k-means on path features**, not asserted |
| 9 | Explainable AI report | `explain_forecast()` — evidence → mechanism → analog → counterargument → failure conditions |
| 10 | Policy impact engine | `InterventionSearch` — costed do-operations, greedy EV ranking |
| 11 | Early warning system | indicators with metric/threshold/lead-time/confidence |
| 12 | Red team | `Adversary` (quantitative) + qualitative challenge set |

---

## The research novelty (what is new here)

**Claim N1 — Proper-scoring-rule supervision of causal mechanism parameters.**
Existing work trains *forecasters* (LLMs, time-series models) on scoring rules, or extracts causal graphs *as labels*. Here the entire stochastic simulator `θ → p(events)` is treated as one trainable program: SPSA (two-sided simultaneous-perturbation gradients with common random numbers) pushes Brier-score gradients **into the hazard/jump/pass-through parameters of the causal mechanism itself**, against a leakage-firewalled replay window of already-resolved events (Feb→Jun 2026).
*Demo result:* Brier 0.194 → **0.129** (−33%), log score improves equivalently, and the trainer autonomously rediscovers a historical truth the expert prior underweighted: war→Hormuz-closure hazard moves 0.06 → 0.23/quarter — i.e., *closure follows war onset fast*, which is exactly what happened (war 28 Feb, closure 4 Mar). Cost paid: a known bias-variance trade (false-positive mass on "Brent>$150" rises to 0.12). All visible in `output/charts/calibration.png`.

**Claim N1b — Identifiability-aware parameter transfer.** The replay window starts in *active war*, so it identifies war-state mechanics strongly but ceasefire-state hazards weakly; naively deploying trained θ forward inflates escalation risk (selection bias). Deployment θ therefore keeps trained values for replay-identified parameters (war→Hormuz hazard, oil jumps, pass-throughs, war de-escalation) and shrinks weakly identified ones toward the expert prior (λ=0.3). Training-vs-deployment regime mismatch handled explicitly rather than ignored.

**Claim N2 — Red-teaming as optimization: min-max forecast bands.**
Phase-12 red-teaming is normally narrative. Here an adversary extremizes each forecast probability over a plausibility ball ‖Δθ‖≤ρ in normalized parameter space (CRN across probes). The reported object is a **min-max band**: "no parameterization a reasonable critic could defend moves this number outside [lo, hi]." Forecasts are then auto-labeled ROBUST/FRAGILE by band width — the dashboard's Red Team tab is generated, not written.

**Claim N3 — Adversarial-conformal composition.**
Split-conformal quantiles of the replay residuals widen the adversarial bands, composing *distributional* robustness (N2) with *calibration* robustness. Stated honestly as a heuristic floor (event exchangeability fails for world events), not a coverage theorem.

**Claim N4 — Policy as amortized search over do-operations.**
Interventions are typed multiplicative do-operations on hazard channels with costs; a greedy submodular-style search maximizes harm-functional reduction per cost under a budget. Output is a ranked portfolio with marginal value-per-cost at each step (Phase 10 as optimization rather than essay).

**Prior-art positioning (checked 11 Jun 2026):** LLM geopolitical forecasters (LLM4Geopolitics; ForecastBench shows LLMs < superforecasters), LLM agent societies (AgentSociety, GenSim), LLM causal-graph extraction (Causal Cartographer; "causal parrots" critique), hybrid TFT+GP event models, Bayesian-network geopolitical forecasting — none, to our knowledge, trains the *simulator's causal parameters* end-to-end on proper scoring rules against resolved events, nor reports min-max adversarial bands as the primary forecast object. That specific combination is the contribution. We cannot guarantee absence of unpublished parallel work.

**Honest limits.** n=10 resolved events is a method demonstration, not statistical validation; hazards remain hand-structured even if now machine-tuned; probabilities are model-conditioned beliefs, not frequencies; the harm functional encodes value judgments. Scale-up path: hundreds of GDELT/ICEWS-resolved events, LLM front-end compiling news into `situation.json` automatically, learned (neural) hazard functions replacing the parametric forms, and a differentiable surrogate to replace SPSA.

---

## Repo layout

```
cassandra-core/
├── core/engine.py          world model + actors + replay events
├── core/phases.py          causal graph, scenarios, explanations, red team
├── novelty/cassandra.py    N1-N4 research layer
├── data/situation.json     facts, signals, analogs, EWIs, explanations (sourced)
├── pipeline.py             12-phase orchestrator
├── cli.py                  command-line interface
├── dashboard_template.html 8-tab self-contained dashboard (no CDN, offline)
├── tests/test_smoke.py     14 tests
└── output/                 report.json, charts/, dashboard.html (generated)
```

## Program blueprint

`docs/BLUEPRINT.md` (also `docs/ARGUS-DT_Blueprint.docx`, 25 pp) is the full **ARGUS-DT national digital-twin program blueprint** built on this prototype: complete Gen-1 architecture (ingestion → temporal causal knowledge graph → hierarchical multi-agent twin → causal/analog/forecast/counterfactual/XAI/policy engines → copilot → national deployment), weaknesses of existing systems (GDELT/ACLED/REsCape/ABM/LLM), breakthrough innovations B1–B8 with mathematical formulations, training/evaluation/benchmark/security/audit/red-team/continuous-learning designs, prototype-to-national roadmap, self-critique, and Gen-2/Gen-3 architectures. Appendix B maps every blueprint component to a runnable module in this repo.

## Disclaimers

Open-source analytic exercise. Not an official intelligence product, not investment/legal advice. Sources for all Phase-1 facts are cited inside `data/situation.json` and the dashboard. A full research paper formalizing N1–N4 is planned as a separate deliverable.
