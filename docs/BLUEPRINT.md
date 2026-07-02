# ARGUS-DT

## National Strategic Intelligence & Societal Digital Twin Program — Complete System Blueprint

**Prepared by:** Office of the Chief Scientist / Chief Systems Architect / Lead Research Director
**Version:** 1.0 — 11 June 2026
**Status:** Program blueprint for a multi-year government R&D effort
**Working prototype:** `cassandra-core` (this repository) is the operating Gen-0 engine; every Gen-1 component below maps to a prototype module that already runs.

> **Scope and ethics note.** ARGUS-DT is a *decision-support and foresight* system: it forecasts, explains, and stress-tests policy. It is explicitly **not** a population-surveillance or influence-conduct system. The Information Domain components are *defensive* (detecting and characterizing influence operations against the public). Civil-liberties guardrails, oversight, and auditability are first-class architecture (§20–§21, Appendix A), not afterthoughts.

---

# Part 0 — Executive Overview

## 0.1 Mission

Give national decision-makers an interactive intelligence copilot that answers, with evidence, calibration, and provenance: *What is likely to happen? Why? What caused it? What if conditions change? Which policy reduces risk, at what cost, with what unintended consequences? What are the early warnings? Which regions are vulnerable? What history is most similar?*

## 0.2 The central design thesis

Every existing approach fails at the same joint: **the connection between narrative knowledge (what analysts read and know) and mechanistic simulation (what models can compute) is hand-made, static, and unscored.** GDELT/ACLED give events without mechanisms; ABMs give mechanisms without evidence-grounding; LLMs give narratives without calibration; statistical forecasters give calibration without explanations or counterfactuals.

ARGUS-DT's thesis: **make the entire pipeline — text → causal structure → simulation → probability — a single trainable, attackable, auditable object**, scored end-to-end on proper scoring rules against events that actually resolved, red-teamed by optimization rather than by essay, and surfaced through a copilot that can only ever answer from the scored pipeline (never from unguarded model priors).

This thesis is already demonstrated at toy scale in the Gen-0 prototype: simulator parameters trained on resolved events (Brier −33%), identifiability-aware deployment transfer, min-max adversarial bands, calibration-excess conformal widening, and greedy expected-value policy search — all running code.

## 0.3 Design principles

1. **No naked numbers.** Every probability ships with a band (adversarial + conformal), an evidence chain, a mechanism, an analog, a counterargument, and failure conditions (prototype Phase 9).
2. **Calibration is the optimization target,** not accuracy theater. Proper scoring rules everywhere; abstention is an allowed output.
3. **Causality before correlation.** The system stores *mechanisms* (structural causal models), uses associations only inside mechanisms.
4. **Adversarial by construction.** Every model has a budgeted attacker; every release is gated on red-team metrics.
5. **Leakage firewall.** Time-locked snapshots; no component may see post-cutoff data during evaluation — enforced by infrastructure, not policy.
6. **Human primacy.** The system recommends and explains; humans decide. Reflexivity (§14-B7) is modeled, not exploited.
7. **Federated truth.** Multiple competing models, not one oracle; disagreement is signal and is surfaced.

## 0.4 Layered architecture at a glance

```
┌────────────────────────────────────────────────────────────────────────┐
│ L7 COPILOT     conversational intelligence copilot · dashboards · API  │
├────────────────────────────────────────────────────────────────────────┤
│ L6 DECISION    policy optimizer · counterfactual engine · EWI service  │
├────────────────────────────────────────────────────────────────────────┤
│ L5 INFERENCE   forecasting ensemble · calibration/conformal · bands    │
├────────────────────────────────────────────────────────────────────────┤
│ L4 SIMULATION  hierarchical multi-agent twin · system dynamics · ABM   │
├────────────────────────────────────────────────────────────────────────┤
│ L3 REASONING   causal engine (SCM store) · analog retrieval · XAI      │
├────────────────────────────────────────────────────────────────────────┤
│ L2 KNOWLEDGE   temporal causal knowledge graph · case library · GIS    │
├────────────────────────────────────────────────────────────────────────┤
│ L1 INGESTION   connectors · extraction · fusion · quality · firewall   │
├────────────────────────────────────────────────────────────────────────┤
│ L0 PLATFORM    enclaves · provenance ledger · scheduling · MLOps · IAM │
└────────────────────────────────────────────────────────────────────────┘
Cross-cutting: security (§20) · audit (§21) · red team (§24) · continuous learning (§25)
```

Seven domains (social, political, economic, security, geographic, environmental, information) are **schemas over shared engines**, not separate stacks: each domain contributes variable types, event ontologies, and mechanism templates to L2–L4.

---

# Part I — Gen-1 System Design

*Each component: purpose, I/O, algorithms, data structures, compute, scalability, failure modes, security — then a prototype pointer.*

## 1. Complete System Architecture

**Purpose.** Bind L0–L7 into one auditable pipeline where every answer is traceable to data, mechanism, and scoring history.

**Component inventory.** Ingestion mesh (§2) → Temporal Causal Knowledge Graph TCKG (§3) → Causal Engine (§5) → Twin Simulator (§4) → Forecast Ensemble (§7) → Counterfactual Engine (§8) → XAI (§9) → Policy Optimizer (§10) → Copilot (§11), on platform (§12).

| Attribute | Specification |
|---|---|
| Inputs | All-source data (licensed, open, classified by enclave); user questions; analyst annotations |
| Outputs | Forecasts w/ robust bands; explanations; counterfactuals; policy portfolios; EWI alerts; audit records |
| Algorithms | Orchestrated DAG of services; event-driven recompute; versioned model registry |
| Data structures | TCKG (temporal property graph); SCM store (typed DAGs + mechanisms); scenario ensembles (path tensors); provenance ledger (append-only Merkle log) |
| Compute | Steady-state: ~2–5k GPU + 50k CPU cores national-scale; burst: simulation campaigns 10× |
| Scalability | Geographic sharding (region cells), horizon sharding, model-parallel ensembles; eventual consistency for KG, strict for ledger |
| Failure modes | Cascading stale-data poisoning → mitigated by freshness SLAs + quarantine; ensemble collapse to one model → diversity penalties (§7) |
| Security | Enclave separation by classification; cross-enclave one-way diodes for data-down, summary-up |

**Prototype pointer.** `pipeline.py` is this orchestration at module scale (12 phases, 3-second cycle).

## 2. Data Ingestion Architecture

**Purpose.** Convert the world's signal exhaust into typed, deduplicated, provenance-stamped, *deception-weighted* observations.

**Source classes.** (a) event databases (GDELT-class firehose, ACLED-class curated); (b) official statistics (IMF/WB/national); (c) markets (commodities, FX, sovereign spreads, prediction markets); (d) satellite imagery & derived indices (nightlights, agriculture, shipping AIS, flaring); (e) media/social text streams; (f) climate/seismic sensors; (g) classified feeds (enclave-bound); (h) analyst reports.

**Pipeline stages.** Connect → normalize (schema + units + geocode to H3 cells + entity-resolve) → deduplicate (MinHash + embedding clusters) → extract (LLM information extraction into event/claim frames with source spans) → **credibility & deception weighting** (per-source reliability priors updated by later verification; coordinated-behavior detection for info-ops) → fuse (Bayesian fusion of conflicting claims with explicit disagreement records) → publish to TCKG with full provenance → snapshot into the **leakage firewall** (immutable time-indexed shards; evaluation jobs can only mount shards ≤ cutoff).

| Attribute | Specification |
|---|---|
| Inputs | ~10⁶–10⁷ raw items/day national scale |
| Outputs | Typed observations: `Event(type, actors, location-H3, time, magnitude, confidence, sources[])`, `ClaimFrame`, `SeriesPoint` |
| Algorithms | LLM-IE with constrained decoding to schemas; MinHash/LSH dedup; Bayesian source-reliability (Beta per source×topic); graph-based coordination detection (co-temporal posting graphs) for influence ops |
| Data structures | Kafka-class log → columnar lake (time, H3, type partitions) → graph upserts |
| Compute | IE is the cost center: ~1–3 GPU-ms/item ⇒ ~50–200 GPU steady |
| Scalability | Stateless extractors; partition by source; backfill via batch |
| Failure modes | **Poisoning via fabricated local media** (top risk) → multi-source quorum for high-impact claims + provenance-weighted fusion + anomaly quarantine; entity-resolution drift → periodic re-resolution with stable IDs |
| Security | Source identities protected; classified connectors enclave-only; extractor prompts/configs signed |

**Prototype pointer.** `data/situation.json` is the hand-built stand-in for this layer's output (14 sourced facts, scored signals).

## 3. Knowledge Graph Architecture (TCKG)

**Purpose.** One queryable memory: *what happened, who did it, where, what claims exist, what mechanisms connect them, and what was believed when.*

**Design.** A **bitemporal, geospatial, causal** property graph.

- **Node types:** Actor (state, org, leader, group), Event, Location (H3 hierarchy), Variable (typed time series: inflation, sentiment index, river level…), Claim, Source, Mechanism (reified causal edge), Case (historical episode), Policy/Intervention, Narrative (info-domain object).
- **Edge types:** participated-in, located-at, supports/contradicts (claims), **causes(mechanism, sign, lag, strength-distribution, evidence[])**, precedes, analog-of, governs, targets.
- **Bitemporality:** every assertion carries (valid-time, transaction-time) → "what did we believe on date X" queries — required for honest backtests and audits.
- **Causal sub-graph = SCM store:** mechanisms are first-class nodes carrying parametric form + parameter posterior + identification status (§5).

| Attribute | Specification |
|---|---|
| Inputs | Fused observations (§2); mechanism updates (§5); analyst edits (signed) |
| Outputs | Subgraph queries; variable panels for simulation; case bundles for analogs; narrative maps |
| Algorithms | Incremental entity resolution; temporal indexing (interval trees); H3 spatial joins; GNN-based link prediction *flagged as hypothesis edges only* |
| Data structures | Distributed property graph (1–10 B edges national scale) + columnar series store + vector index for text/embedding retrieval |
| Compute | Modest vs simulation: ~100 nodes cluster; vector index on accelerators |
| Scalability | Shard by H3 super-cells × time; hot replicas for copilot reads |
| Failure modes | Ontology rot → versioned schemas + migration tests; hypothesis edges leaking into causal store → identification-status gate (only `identified`/`expert-attested` edges feed simulation) |
| Security | Cell-level classification labels; query-time redaction; edit ledger |

**Prototype pointer.** `situation.json` causal_nodes/edges + explanations = micro-TCKG with mechanism text.

## 4. Multi-Agent Simulation Architecture (the Twin)

**Purpose.** A hierarchical society-scale simulator that turns causal state into distributions over futures — the *only* component allowed to generate forecasts of system dynamics.

**Three tiers, coupled:**

- **Tier S (strategic actors, ~10²):** states, leaderships, organized armed groups, central banks. Bounded-rational policies: softmax over utility features (survival, revenue, audience costs, deterrence credibility), parameters trainable (§16). *Prototype: `actor_stances()` for Iran/US/Russia/PRC.*
- **Tier M (mesoscale populations, ~10⁴–10⁵ cells):** H3-cell populations with state vectors (grievance, income, food access, displacement propensity, sentiment, narrative exposure). Dynamics: coupled stochastic difference equations on the cell graph (diffusion along adjacency + media graph). This is where unrest, migration, sentiment, community tension live.
- **Tier B (behavioral micro-samples, ~10⁴ LLM-agent panels, offline):** generative-agent panels used *only* to fit/validate Tier-M response functions (e.g., protest participation vs grievance×repression) — never in the online loop (cost + validity). AgentSociety-class systems are calibration instruments here, not the twin itself.

**Coupling:** Tier-S actions shift Tier-M fields (repression, subsidies, mobilization); Tier-M aggregates (unrest index, displacement flows) enter Tier-S utilities and macro variables (regime-switching macro core as in prototype: conflict regimes × oil × growth × inflation × food × EM stress).

| Attribute | Specification |
|---|---|
| Inputs | Initial state from TCKG; θ (trained mechanism params); intervention handles (do-operations); shock distributions |
| Outputs | Path tensors: variables × cells × quarters × N paths; event streams per path |
| Algorithms | Regime-switching SSMs; vectorized categorical transitions; spatial convolution diffusion; common random numbers across policy comparisons; quasi-MC scrambling |
| Data structures | Path tensors (compressed, FP16) ~ N=10⁵ × 10⁴ cells × 40 q × 32 vars ≈ manageable via cell-sharding; per-run manifest (θ hash, seed, snapshot id) |
| Compute | National full-twin campaign: ~10³ GPU-hours; regional slices interactive (<1 min) |
| Scalability | Embarrassingly parallel across paths; spatial domain decomposition; neural surrogates for hot loops (Gen-2) |
| Failure modes | **Validity theater** (fits past, wrong mechanisms) → counterfactual benchmark gates (§18); chaos sensitivity → report path-distribution stats only, never single runs |
| Security | θ and mechanism store are crown jewels (they encode national vulnerability models) — highest enclave |

**Prototype pointer.** `core/engine.py` (Tier-S + macro core; 20k×40q in ~1 s).

## 5. Causal Reasoning Engine

**Purpose.** Maintain the *mechanism layer*: typed structural causal models with parameter posteriors, identification status, and do-calculus services. Answers "why," "what caused," and grounds all counterfactuals.

**Sub-services.**
1. **Mechanism library:** templated SCM fragments per domain (price pass-through, protest diffusion, blockade→trade→price, drought→yield→food price→unrest…), each `M: parents → child` with parametric form, priors, lag structure.
2. **Structure proposal:** LLMs read TCKG text evidence and *propose* mechanism instantiations with sign/lag/strength priors (LLM-as-prior, never LLM-as-verdict — "causal parrots" guarded).
3. **Identification & estimation:** per edge, attempt natural-experiment identification (DiD, synthetic control, IV from weather/geography, RDD on policy thresholds) over TCKG panels; record `identified | estimated-with-confounding-risk | expert-attested | hypothesis`.
4. **End-to-end mechanism training:** parameters additionally trained by proper-scoring-rule supervision through the simulator (§16, prototype-proven).
5. **Do-calculus service:** queries `P(Y | do(X), evidence)` compiled to simulator runs or closed-form where available.
6. **Attribution service:** for "what caused E," compute per-mechanism contribution via path-specific effects + Shapley decomposition over the SCM (§9).

| Attribute | Specification |
|---|---|
| Inputs | TCKG panels + text evidence; resolved events (for E2E training); analyst attestations |
| Outputs | SCM store; effect estimates with CIs; attribution decompositions; identification ledgers |
| Algorithms | LLM-constrained structure proposal; double-ML / synthetic control / IV estimators; Bayesian posterior updates; SPSA/Gumbel gradients for E2E (§15) |
| Data structures | Mechanism nodes in TCKG: `{form, θ-posterior, lags, id-status, evidence[], score-history}` |
| Compute | Estimation jobs CPU-heavy batch; LLM proposal ~GPU-light |
| Scalability | Mechanisms are local (small parent sets) → parallel estimation |
| Failure modes | Confounded estimates dressed as causal → id-status gate + mandatory sensitivity analysis (E-values) on every `estimated` edge; mechanism duplication → canonicalization |
| Security | Mechanism store integrity (signed updates); poisoning via fake natural experiments → source quorum |

**Prototype pointer.** θ-spec + trained hazards in `engine.py`/`cassandra.py`; perturbation-verified causal weights in `phases.py`.

## 6. Historical Analog Retrieval Engine

**Purpose.** Retrieve the most *mechanistically* similar historical episodes — evidence about mechanism, not destiny — with outcomes, policy successes/failures, and divergence warnings.

**Key idea: similarity in causal-state space, not text space.** Each case (e.g., "1973 oil embargo," "Korea 1953 armistice") is stored as a **causal cartridge**: the SCM subgraph active during the episode + trajectory of its variables + interventions tried + outcomes. Query = current SCM neighborhood + state trajectory. Similarity = weighted combination of (a) graph kernel on SCM subgraphs (mechanism overlap), (b) DTW distance on normalized state trajectories, (c) embedding similarity of narrative descriptions — with weights validated against "did the analog's outcome distribution actually help forecast?" (analog usefulness is *scored*, like everything else).

| Attribute | Specification |
|---|---|
| Inputs | Query state (SCM neighborhood + recent trajectories); case library (target: 5,000+ curated episodes, 1800–present) |
| Outputs | Ranked analogs: similarity, matched/unmatched mechanisms, outcome distribution, lessons, divergence factors |
| Algorithms | Weisfeiler–Leman graph kernels; constrained DTW; cross-encoder rerank; usefulness-weight learning (regression of forecast-skill lift on analog features) |
| Data structures | Case = `{SCM subgraph, variable panel, interventions[], outcomes[], sources[]}` |
| Compute | Light; index rebuilds nightly |
| Scalability | Trivial at 10⁴ cases |
| Failure modes | Seductive surface analogs (1914 for everything) → mechanism-overlap floor required; survivorship bias in library → systematic inclusion of non-events (crises that didn't happen) |
| Security | Low; public-history dominated |

**Prototype pointer.** `situation.json` analogs with similarity/lessons; Gen-1 upgrades hand scores to graph-kernel scores.

## 7. Forecasting Engine

**Purpose.** Produce calibrated probability distributions for typed questions across horizons (7d → 10y) by *adversarially weighted ensemble* over heterogeneous forecasters.

**Ensemble members (deliberately diverse families):**
M1 statistical baselines (hierarchical Bayesian autoregressions, gradient-boosted event models — strong, cheap, hard to beat); M2 the Twin (§4) — the only member that can answer counterfactual and mechanism questions; M3 judgmental layer — LLM panels emulating superforecaster protocols (fine-tuned on resolved-question corpora, ForecastBench-style), used for one-off/odd questions; M4 market priors (prediction markets, sovereign spreads) where they exist; M5 analog-implied base rates (§6).

**Aggregation: trained, diversity-regularized, regime-aware stacking.** Weights w(q) depend on question type, horizon, region, and each member's *rolling calibration record*; diversity penalty prevents collapse onto M1; abstention triggered when members disagree beyond threshold *and* historical skill in that stratum is poor.

**Calibration & bands stack (the prototype's signature, scaled):** member forecasts → stacked point → **min-max adversarial band** over mechanism-parameter plausibility ball (§15.3) → **calibration-excess conformal widening** (§15.4) → per-stratum recalibration maps (isotonic/temperature, refit monthly). Output object is always `{p, band[lo,hi], components, calibration-stratum, abstain?}`.

| Attribute | Specification |
|---|---|
| Inputs | Question (typed); TCKG state; ensemble members; scoring history |
| Outputs | Forecast objects + full lineage; EWI threshold crossings |
| Algorithms | Stacking with monotone calibration; CRPS for continuous, Brier/log for binary; quantile regression for fans |
| Data structures | Question registry (every question versioned, resolvable, scored); forecast ledger |
| Compute | Dominated by Twin campaigns; stacking trivial |
| Scalability | Question-parallel; shared simulation campaigns serve many questions |
| Failure modes | Goodharting the question registry (optimizing easy questions) → skill reported per stratum incl. hard strata; regime breaks → change-point detectors widen bands automatically |
| Security | Forecast ledger tamper-evident (audit §21) |

**Prototype pointer.** `event_probs()` + `Adversary` + `ConformalLayer` + robust-band chart.

## 8. Counterfactual Simulation Engine

**Purpose.** Answer "what if" (interventional) and "what would have happened" (retrospective counterfactual) with explicit assumptions.

**Modes.**
- **Interventional (futures):** `P(Y | do(policy), state)` — Twin runs with intervention handles; paired-path design (common random numbers) isolates policy effect per path → effect *distributions*, not deltas of means. *Prototype-proven (`hazard_mods`, CRN).*
- **Retrospective (twin-network):** for "would the war have happened without X?", abduction–action–prediction over the SCM: infer exogenous noise posterior from observed history (particle smoothing over the regime-switching SSM), pin noise, flip X, re-simulate. Reported with **identification caveats auto-attached** (which mechanisms were `hypothesis`-grade).
- **Stress/conjunction:** systematic 2–3-way shock conjunctions (the black-swan basket generator), scored for cascade depth.

| Attribute | Specification |
|---|---|
| Inputs | Baseline state/history; intervention or counterfactual clause (typed do-expressions) |
| Outputs | Paired path distributions; effect CIs; cascade maps; assumption ledger per answer |
| Algorithms | CRN paired simulation; particle smoothing for abduction; variance reduction (antithetic, control variates vs baselines) |
| Data structures | Counterfactual job manifest (fully reproducible: snapshot, θ, seeds, clause) |
| Compute | 2× baseline campaign per query class; cached by clause hash |
| Scalability | Same as Twin |
| Failure modes | Users reading retrospective counterfactuals as facts → UI forces assumption display; identification-grade gating |
| Security | Counterfactuals on adversary vulnerabilities are highly sensitive → enclave + need-to-know |

## 9. Explainable AI Engine

**Purpose.** Make every output *arguable*: evidence, mechanism path, quantitative attribution, analog, counterargument, failure conditions — generated from structure, not free-form LLM prose.

**Methods.** (a) **Structural attribution:** Shapley over SCM mechanism contributions to a forecast delta (vs reference state); path-specific effects for "via what channel." (b) **Evidence chains:** every claim links to TCKG observations with source spans (prototype Phase 9 pattern). (c) **Counterargument generator:** the adversary's (§15.3) worst-case parameterization is *narrated* — "the strongest defensible case against this number." (d) **Faithfulness guard:** LLM verbalizes only from a structured explanation object; a checker verifies every sentence maps to object fields (no unsupported claims); failures rendered as the object itself.

| Attribute | Specification |
|---|---|
| Inputs | Forecast/counterfactual lineage; SCM; TCKG evidence |
| Outputs | Explanation objects + verified natural-language renderings |
| Algorithms | SCM-Shapley (sampling approximations); path effects; constrained generation + entailment checking |
| Data structures | `Explanation{evidence[], mechanism-path[], attribution{}, analog, counter, failure[], confidence}` |
| Compute | Light |
| Scalability | Cached per forecast version |
| Failure modes | Plausible-but-unfaithful narration → entailment gate (hard fail closed); attribution instability → report ranges across seeds |
| Security | Explanations can leak sources → redaction-aware rendering per clearance |

**Prototype pointer.** `explain_forecast()` objects + dashboard Evidence tab.

## 10. Policy Optimization Engine

**Purpose.** Search intervention space for portfolios that reduce a *governed* harm functional under budget/feasibility/legality constraints, with unintended consequences traced, robustness checked, and value judgments exposed as parameters.

**Formulation (§15.5):** maximize robust expected harm-reduction per cost over portfolios of typed do-operations; constraints: budget, political-feasibility scores (themselves forecasts), legal/ethical hard constraints (constraint set is signed policy, not model output). **Unintended consequences:** for each candidate, automatic second/third-order scan = attribution of *all* tracked harms/benefits deltas, not just targeted ones; flag any harm increase > threshold. **Robustness:** evaluate under adversarial θ (the min-max ball) and across ensemble members — recommend only interventions whose sign survives.

| Attribute | Specification |
|---|---|
| Inputs | Harm functional weights (signed by decision authority); intervention library (typed handles, costs, lags, feasibility); Twin |
| Outputs | Ranked portfolios; marginal value/cost curves; consequence ledgers; robustness certificates |
| Algorithms | Greedy submodular-style + local search (prototype); Bayesian optimization over continuous handles; constrained multi-objective (ε-constraint) for tradeoff surfaces |
| Data structures | Intervention cards `{handles, cost curves, lags, prerequisites, legality tags}` |
| Compute | ~10²–10³ Twin evaluations per study → surrogate-assisted (Gen-2) |
| Scalability | Portfolio search parallel; warm-start from similar past studies |
| Failure modes | **Value-laundering** (politics hidden in weights) → weights are visible, versioned, signed; optimizer exploiting model error → robustness certificate requirement |
| Security | Recommendation studies are decision-sensitive → highest audit density |

**Prototype pointer.** `InterventionSearch` (31% harm reduction portfolio, marginal value/cost steps).

## 11. Conversational Intelligence Copilot

**Purpose.** The only user-facing brain: translate natural language into *typed* engine calls; compose grounded answers; never answer from unguarded LLM priors.

**Question compiler.** NL → typed intent over a closed grammar: `FORECAST(event-spec, horizon)`, `EXPLAIN(observation)`, `CAUSE(event)`, `WHATIF(do-clause, target)`, `POLICY(objective, constraints)`, `EWI(domain, region)`, `VULNERABILITY(region-set, hazard)`, `ANALOG(situation)`. Ambiguity → clarifying question with candidate parses shown. Every user question becomes a registry question (versioned, eventually scored — the copilot's own usage grows the training set §25).

**Answer composer.** Calls engines, receives objects (forecast + band + explanation + analogs), renders per persona (leader: 5 lines + risk band; analyst: full lineage with drill-down). Hard rules: numbers only from engines; "I don't know" is a first-class answer (abstention); disagreement between ensemble members shown, not averaged away when wide; every answer carries a permalink to its reproducible manifest.

| Attribute | Specification |
|---|---|
| Inputs | NL questions; clearance context; persona |
| Outputs | Grounded answers, briefs, alerts, follow-up suggestions |
| Algorithms | Constrained semantic parsing (grammar-restricted decoding); retrieval over question registry for precedents; persona templates |
| Data structures | Closed intent grammar; session graphs (multi-turn state) |
| Compute | LLM serving ~10² concurrent analysts |
| Scalability | Stateless parse/render; engine calls cached |
| Failure modes | **Prompt injection via quoted documents** → all retrieved text is data-tagged, never instruction-tagged; parser allow-list; **hallucinated grounding** → entailment gate from §9 applies to copilot output too |
| Security | Per-question authorization against cell-level labels; full session audit |

**Prototype pointer.** Dashboard 8 tabs = the non-conversational ancestor; question grammar maps 1:1 to the 9 user questions in the mission statement.

## 12. National-Scale Deployment Architecture

| Attribute | Specification |
|---|---|
| Topology | 3 enclaves (OPEN-research / OFFICIAL / SECRET-compartmented), each a full stack; data flows down via vetted pipelines, only signed summaries flow up; regional nodes (federated states/commands) run twin slices, sync mechanisms not raw data |
| Inputs/Outputs | As §2/§7–§11 per enclave |
| Algorithms | Federated mechanism averaging (share θ posteriors, not data); CRDT-style KG merge for non-causal facts |
| Data structures | Per-enclave ledgers; cross-enclave manifest registry |
| Compute | Anchor sites: 2 national compute facilities (active-active), regional inference points |
| Scalability | Add regional nodes without central re-architecture (mechanism-level federation) |
| Failure modes | Split-brain KGs → CRDT merge + periodic reconciliation; enclave summary leakage → summary DLP gates |
| Security | Hardware roots of trust; signed model artifacts; air-gapped SECRET training; insider-threat: dual-control on mechanism store writes (§20) |

---

# Part II — Research Program

## 13. Weaknesses of Existing Approaches

| System / class | What it does well | Fatal gap ARGUS-DT closes |
|---|---|---|
| **GDELT** | Planetary event firehose, recency | No mechanisms, no dedup discipline, severe source noise; events ≠ understanding; no forecasting, no calibration |
| **ACLED** | Curated conflict events, quality coding | Coverage limited to conflict; descriptive, not predictive; no causal layer |
| **REsCape-class conflict models** | Structured conflict scenario exploration | Hand-built, static parameters; no scoring against resolved events; no uncertainty discipline; single-domain |
| **Traditional ABM (incl. generative-agent societies)** | Mechanism richness, emergence | Calibration theater: fit to stylized facts, never trained on proper scoring rules; validity unmeasurable; LLM-agent societies add cost + bias with no scoring loop |
| **Standard LLM systems** | Knowledge breadth, narrative fluency | Uncalibrated (ForecastBench: below superforecasters); no causal commitments; temporal leakage in evals; answers from priors, not evidence; prompt-injectable |
| **Statistical EWS (ViEWS-class)** | Honest scoring, good AUC on conflict onset | Correlational: cannot answer why/what-if/which-policy; rigid question set |
| **Prediction markets / superforecasters** | Best-in-class calibration | No mechanisms (can't explain or do counterfactuals); coverage sparse, slow, expensive; reflexivity unmodeled |
| **All of the above** | — | **None trains the text→structure→simulation→probability pipeline end-to-end on outcomes; none ships adversarial bands; none firewalls leakage by infrastructure; none scores its own explanations** |

## 14. Breakthrough Innovations (B1–B8)

*B1–B4 are running in the prototype (novelty/cassandra.py); B5–B8 are the Gen-1→Gen-3 research arc.*

- **B1 — Proper-scoring-rule supervision of causal mechanisms.** Train simulator mechanism parameters end-to-end on Brier/CRPS against resolved events, not on fitting historical curves. *Demonstrated: −33% Brier; rediscovered war→closure speed from outcomes alone.*
- **B2 — Identifiability-aware regime transfer.** Deployment parameters = trained values where the training window identifies them, prior-shrunk elsewhere; formalizes training-regime ≠ deployment-regime, the silent killer of backtested systems.
- **B3 — Min-max adversarial bands as the forecast object.** Red-teaming as optimization over a plausibility ball; report `[min, max]` over defensible parameterizations. Verdicts (ROBUST/SENSITIVE/FRAGILE) generated, not narrated.
- **B4 — Calibration-excess conformal composition.** Conformal widening with nonconformity = residual *beyond* a perfectly calibrated forecaster's expected residual (raw |p−y| over-penalizes honest mid-range probabilities); composed with B3 bands.
- **B5 — Narrative-to-Mechanism Compiler (NMC).** An LLM front-end that reads the day's evidence and emits *typed SCM deltas with uncertainty* (new mechanism instances, parameter shifts, regime flags) — trained not on annotation agreement but **through the pipeline on forecast skill** (REINFORCE/Gumbel through structure choices, §15.6). Closes the loop that today is human-made: the model learns to read the news *in units of mechanism*.
- **B6 — Amortized Neural Twin.** Distill Tier-M ABM dynamics into neural surrogates conditioned on (state, θ, do-clause) with simulation-consistency training; makes national counterfactuals interactive (<1 s) and enables gradient-based policy search; periodic re-grounding against the full ABM to prevent surrogate drift.
- **B7 — Performative (reflexive) forecasting.** Decision-grade forecasts change behavior. Model the announcement as an intervention: seek fixed points p* = F(state, announce(p*)) (§15.7); report both *shadow* (unannounced) and *performative* (fixed-point) forecasts. No deployed system does this; it is the difference between forecasting and steering, made explicit and governable.
- **B8 — Deception-robust fusion.** Treat ingestion as a game vs an adaptive adversary who fabricates correlated sources: quorum-weighted fusion with coordination-graph detection, adversarial data ablations in evaluation (forecast must survive removal/poisoning of any single source family), and *information-warfare attribution* as a first-class forecast type.

## 15. Mathematical Formulations

**15.1 World model.** Latent regime-switching SSM: regimes $r_t \sim \mathrm{Cat}(\pi_\theta(r_{t-1}, s_t, a_t))$, continuous state $x_{t+1} = f_\theta(x_t, r_t, a_t) + g_\theta(\cdot)\,\epsilon_t$, agents $a_t = \mathrm{softmax}_\beta(u_\phi(x_t, r_t))$. Forecast functional for question $q$ with extractor $h_q$: $p_\theta(q) = \mathbb{E}_{\epsilon}[h_q(x_{1:H}, r_{1:H})]$.

**15.2 Calibration training (B1).** $\min_\theta\; \mathbb{E}_{(q,y)\sim\mathcal{D}_{\le T}} \big[ (p_\theta(q) - y)^2 \big] + \lambda \lVert z(\theta) - z(\theta_0)\rVert^2$ with $z$ the normalized coordinates and $\theta_0$ the expert prior; gradients by SPSA, $\hat g = \frac{L(z + c\Delta) - L(z - c\Delta)}{2c}\,\Delta$, $\Delta_i \in \{\pm 1\}$, common random numbers both sides; or Gumbel-softmax relaxation of categorical transitions where differentiable surrogates exist (Gen-2). Replace Brier with CRPS for continuous $y$.

**15.3 Adversarial bands (B3).** For each $q$: $[\,\min_{\delta \in B_\rho} p_{\theta+\delta}(q),\; \max_{\delta \in B_\rho} p_{\theta+\delta}(q)\,]$, $B_\rho = \{\delta : \lVert \delta \rVert_z \le \rho\}$ (tractable surrogate for a KL ball on path measures). Solved by random-direction probes + greedy ascent; CRN across probes. Distributionally-robust training variant: $\min_\theta \max_{\delta \in B_\rho} L(\theta + \delta)$.

**15.4 Calibration-excess conformal (B4).** Nonconformity $s_i = \max(0, |p_i - y_i| - 2p_i(1-p_i))$ (excess over a calibrated forecaster's expected absolute residual); band widening by $\hat q_{0.8}(s)$ on a held-out resolved set; stated as heuristic floor (exchangeability fails for world events).

**15.5 Policy optimization.** Portfolio $\Pi \subseteq \mathcal{I}$, do-handles $m_\Pi$: $\max_\Pi \; \min_{\delta \in B_\rho} \; \frac{ H_{\theta+\delta}(\emptyset) - H_{\theta+\delta}(m_\Pi) }{ C(\Pi) } \;\; \text{s.t.}\; C(\Pi) \le B,\; \Pi \models \text{legal/feasibility constraints}$, harm functional $H_\theta(m) = \mathbb{E}[\, w^\top \mathrm{harms}(x_{1:H}; m) \,]$ with signed, versioned $w$. Greedy + local search; submodularity holds approximately for non-interacting handles (verified empirically per study).

**15.6 NMC training (B5).** Compiler $q_\phi(\Delta G \mid \text{text}_t)$ over typed graph deltas; pipeline loss $L(\phi) = \mathbb{E}_{\Delta G \sim q_\phi} [\, \mathrm{Brier}(p_{\theta(\Delta G)}, y) \,]$; gradient $\nabla_\phi L = \mathbb{E}[\, (\mathrm{Brier} - b)\, \nabla_\phi \log q_\phi(\Delta G) \,]$ (REINFORCE with learned baseline $b$; Gumbel relaxation for edge-weight deltas); KL regularizer to the supervised-extraction posterior keeps proposals linguistically grounded.

**15.7 Performative fixed point (B7).** Announcement-aware forecast: $p^* = F_\theta(s, \mathrm{announce}(p^*))$; existence via Brouwer on $[0,1]^k$ for continuous $F$; compute by damped iteration $p_{k+1} = (1-\eta) p_k + \eta F(s, p_k)$; report $(p^{\text{shadow}}, p^*)$ and the gap as a *steering coefficient* — a governance quantity (large gap ⇒ the act of forecasting is policy).

**15.8 Analog metric.** $\mathrm{sim}(c_1, c_2) = \alpha\, K_{WL}(G_1, G_2) + \beta\, e^{-\mathrm{DTW}(X_1, X_2)} + \gamma \cos(e_1, e_2)$, with $(\alpha,\beta,\gamma)$ fit to maximize forecast-skill lift when analog outcome distributions are pooled into M5.

## 16. Training Methodology

1. **Stage 0 — supervised grounding:** extraction models on annotated event/claim corpora; mechanism priors from expert elicitation + literature mining.
2. **Stage 1 — identification:** estimate every estimable mechanism from panels (§5.3); freeze id-status ledger.
3. **Stage 2 — end-to-end calibration (B1):** rolling-origin curriculum over historical windows: train on questions resolving in $[T_0, T_1]$, validate $[T_1, T_2]$, never touch $> T_2$; thousands of auto-generated questions (GDELT/ACLED-resolvable: onset, escalation, displacement, price thresholds, election outcomes) + curated hard sets.
4. **Stage 3 — adversarial hardening:** DRO training (§15.3); data-ablation training (B8): random source-family dropout during training so no single feed is load-bearing.
5. **Stage 4 — NMC loop (B5):** compiler trained through frozen-then-unfrozen simulator; alternating optimization (compiler ↔ mechanisms) with trust-region steps to prevent co-adaptation collapse.
6. **Stage 5 — judgmental distillation:** M3 fine-tuned on resolved-question reasoning traces (superforecaster rationale corpora), scored by proper rules, never on agreement with the Twin (independence preserved for ensemble diversity).
7. **Ongoing — continuous learning (§25)** with frozen baselines and ratchet gates.

**Leakage firewall (infrastructure):** training jobs mount immutable snapshots ≤ cutoff; lineage checker rejects any artifact whose ancestry includes post-cutoff shards; LLM members are themselves snapshot-pinned models with documented cutoffs (post-cutoff contamination measured by canary questions — events the model cannot know — and corrected by stratified discounting).

## 17. Evaluation Framework

- **Primary:** Brier/log (binary), CRPS (continuous), per stratum {domain × horizon × region × question-hardness}; calibration curves + ECE; PIT histograms for fans; sharpness *conditional on calibration*.
- **Skill referenced:** vs M1 baselines, vs prediction markets where available, vs human superforecaster panels (paid, blinded, n≥30 per question set), vs persistence/climatology.
- **Counterfactual validity:** §18's COUNTERFACT-GEO (synthetic worlds with known SCMs) — the only place ground-truth counterfactuals exist; metric: interventional-distribution Wasserstein error.
- **Explanation faithfulness:** perturbation tests (delete claimed evidence → forecast must move in claimed direction); entailment-gate pass rate; human analyst adjudication samples.
- **Robustness:** performance under §24 attack suite (source ablation, poisoning, prompt injection, θ-ball).
- **Reflexivity:** steering coefficient reported per deployed forecast class (§15.7).
- **Protocol:** all evaluation behind the leakage firewall; preregistered metrics per release; results in the public (OPEN-enclave) technical report for unclassified strata — external reproducibility is a feature, not a risk.

## 18. Benchmark Datasets (to be built and released, OPEN enclave)

1. **RETRO-CAST:** 50k+ auto-resolved historical questions (1995–present) spanning all 7 domains, each with frozen evidence snapshots at ask-time (the leakage-firewalled retrodiction suite); strata for hardness; includes *non-events* (negatives) to kill survivorship bias.
2. **COUNTERFACT-GEO:** families of synthetic societies generated from known SCMs (varying topology, noise, regime structure), with full interventional ground truth; graded difficulty; the counterfactual-validity yardstick no real-world data can provide.
3. **POLICY-TRACE:** 500+ historical interventions (sanctions, ceasefires, subsidies, rate shocks, dam releases…) with synthetic-control estimated effects + uncertainty, for policy-engine validation against history.
4. **DECEPTION-NET:** red-team-generated correlated-source poisoning corpora for B8 evaluation.
5. **ANALOG-500:** curated causal cartridges with expert-rated cross-similarities for §6 metric learning.

## 19. Dashboard & User Experience

**Personas:** Principal (minister/commander): 1-screen risk board, 5-line answers, bands always visible, "what changed since yesterday" diffs. Analyst: full lineage drill-down (prototype's 8-tab dashboard is the seed), question composer, evidence editing with signed provenance. Planner: policy studio — portfolio builder on top of §10 with live marginal value/cost curves. Watch officer: EWI wall — §11 indicators, threshold states, lead-time clocks.

**Uncertainty grammar (uniform):** every number renders as `center [band]` + verdict chip (ROBUST/SENSITIVE/FRAGILE) + stratum calibration badge ("in this stratum, our 70% claims verified 68% of the time, n=412"). Color encodes *band width*, not just level. Abstentions render as abstentions, never as 50%.

**Interaction:** copilot pane on every view; every chart element queryable ("why is this band wide?" → §9 object); scenario scrubbing (drag oil price, watch downstream fans recompute via Gen-2 surrogates); brief generation with auto-citations.

## 20. Security Architecture

**Threat model:** nation-state APT, insider threat, data poisoning (B8), model theft (θ = national vulnerability map), prompt injection, inference attacks on classified strata via OPEN answers.

Controls: enclave separation (§12) with one-way diodes; hardware root of trust + signed artifacts (models, mechanism updates, dashboards); dual-control human review on mechanism-store writes and harm-weight changes; query-time cell-level authorization; differential-privacy noise on cross-enclave aggregate summaries; canary mechanisms (fake entries) for exfiltration tracing; full prompt/response logging with anomaly detection (insider misuse of copilot); supply chain: vendored dependencies, reproducible builds, model provenance attestation; rate-limited and clearance-scoped counterfactual queries on adversary vulnerabilities.

## 21. Auditability & Transparency

- **Provenance ledger:** append-only Merkle log over: ingestion batches, mechanism changes, θ versions, forecast issuances, recommendation studies, copilot sessions. Any answer → `argus://manifest/<hash>` reproduces it bit-for-bit (snapshot + θ + seeds + code version).
- **Decision records:** when a recommendation is exported, a signed record binds: question, answer, bands, assumptions, harm-weights, approver. Years later, "why did we act" is answerable.
- **Model cards & mechanism cards:** every mechanism carries id-status, evidence, score history; every model release carries stratum skill tables.
- **External audit interface:** OPEN-enclave replica + RETRO-CAST results published; independent auditors can re-run unclassified evaluation.
- **Right-of-reply:** analysts can file signed dissents attached to any forecast; dissents travel with the forecast everywhere it renders.

## 22. Confidence Calibration Methods

Hierarchical recalibration: global → domain → stratum isotonic/temperature maps, refit monthly on rolling resolved sets, with shrinkage toward parent stratum where n is small. Abstention policy: abstain when (a) ensemble dispersion > stratum threshold, (b) stratum ECE > gate, or (c) question maps to no identified mechanism (forced "we cannot answer this causally yet" honesty). Verbal-numeric contract: fixed mapping (e.g., "likely" = 60–80%) enforced in all renderings (NATO-style standardization). Score-history badges (§19) make calibration *legible* to users, which disciplines the whole program.

## 23. Adversarial Robustness Methods

(see B3, B8, §16 stages 3–4, §20) — summarized: DRO over mechanism balls; source-family dropout training; quorum fusion with coordination detection; injection-hardened copilot (data/instruction tagging, grammar-constrained parsing); canary questions for LLM contamination; surrogate-drift re-grounding (B6); release gates on the §24 attack suite.

## 24. Red-Team Evaluation Framework

**Standing structure:** an internal adversarial cell (humans + automated attackers) with its own budget and *publication right* (reports go to oversight unredacted).

**Quantitative attack suite (release gate):** θ-ball extremization (B3) — fraction of headline forecasts that flip verdict class; source poisoning campaigns (DECEPTION-NET) — max forecast displacement per poisoned-source budget; prompt-injection corpus — copilot grounding-violation rate (must be 0 on hard gate); leakage probes — canary recall; Goodhart probes — skill on adversarially selected hard strata vs reported average.

**Human campaigns:** quarterly scenario exercises where the red team constructs a deception narrative end-to-end (fake sources → fake mechanism → wrong recommendation) and measures how far it travels before quarantine; postmortems are ratchet inputs (§25).

**Scoring:** every attack class has a metric and a threshold; release requires all gates green + sign-off by the red-team lead (who reports outside the program chain).

## 25. Continuous Learning Architecture

Event-resolution feedback: question registry auto-resolves against TCKG; scores stream into stratum ledgers; recalibration maps refit monthly; mechanism re-estimation triggered by score degradation (CUSUM drift detectors per mechanism). Ratchet evaluation: frozen baseline models from every release re-scored forever; a new release ships only if it beats its ancestors on frozen strata (no silent regressions). NMC online loop: daily compiler proposals land as `hypothesis` mechanisms; promotion to simulation requires id-status upgrade or accumulating score evidence (B1 loop). Human feedback: analyst dissents and adjudications become training signal with provenance. Catastrophic-forgetting guard: per-stratum replay buffers; regime-break detection widens bands and raises abstention thresholds automatically while retraining runs.

## 26. Implementation Roadmap

| Phase | Horizon | Scope | Exit criteria (kill / proceed gates) |
|---|---|---|---|
| **0 — Prototype** | done | `cassandra-core`: B1–B4 demonstrated end-to-end at module scale | ✅ shipped (this repo): −33% Brier, bands, portfolio search, 14 tests |
| **1 — Pilot** | 0–18 mo | One region × three domains (economic, security, environmental); RETRO-CAST v1 (10k questions); ingestion for 50 sources; Twin Tier-S+M at 10³ cells; copilot alpha for 20 analysts | Beat M1 baselines + market priors on ≥60% of pilot strata; calibration ECE <0.05; red-team gates defined and passing |
| **2 — Multi-domain federation** | 18–42 mo | All 7 domains; 3 regions + federation protocol; NMC (B5) in shadow mode; amortized twin (B6) for interactive counterfactuals; benchmark suite public; policy studio with 2 real decision studies | NMC shadow skill ≥ human-curated mechanisms on 12-mo rolling; counterfactual validity on COUNTERFACT-GEO within tolerance; 2 independent audits clean |
| **3 — National deployment** | 42–72 mo | Full enclave topology; 24/7 watch; performative forecasting (B7) governed and live for selected classes; continuous-learning ratchet operating | Sustained skill > all reference classes incl. superforecaster panel on ≥70% strata; zero grounding-violation incidents in production year; oversight regime ratified |
| **Parallel R&D track** | continuous | Gen-2/Gen-3 research (§28–§29), publications from OPEN enclave | Top-venue publications; external replication of B1/B3/B5 results |

**Team shape (steady state):** ~12 research scientists (causal ML, simulation, NLP, forecasting science), ~20 engineers (data, platform, graph, frontend), ~8 domain analysts, 4 red team, 3 ethics/oversight liaison, security staff. Phase-1 can start with 8 people and the prototype.

---

# Part III — Self-Critique and Next Generations

## 27. Critique of the Gen-1 Architecture (adversarial pass on my own design)

1. **The mechanism bottleneck is still human-shaped.** Gen-1's SCM templates are expert-seeded; NMC only arrives in Phase 2. Until then the system inherits its authors' blind spots — exactly the failure mode of every prior conflict model. *Severity: high.*
2. **Tier-M validity is unproven at scale.** Cell-level unrest/migration dynamics fit on history may be confounded folklore; COUNTERFACT-GEO validates the *machinery*, not the *real-world mechanisms*. Honest status: interventional claims at mesoscale will carry `estimated-with-confounding-risk` for years. *Severity: high.*
3. **Question-registry Goodharting.** Auto-generated resolvable questions over-sample the measurable (prices, event counts) vs the strategic (intentions, legitimacy). Skill numbers will flatter the system where it matters least. Mitigation (hard strata) is partial. *Severity: medium-high.*
4. **Ensemble independence erodes.** Members share the TCKG; correlated input errors (poisoned upstream) defeat diversity. B8 helps; doesn't cure. *Severity: medium.*
5. **Reflexivity governance is unsolved.** B7 measures steering; it does not tell a democracy *who may steer*. A forecast with a large steering coefficient is a policy instrument wearing a science costume — the architecture surfaces this but cannot resolve it. *Severity: structural.*
6. **Compute aristocracy.** The min-max + conformal + ensemble stack prices out fast-moving crises (bands need campaigns). Gen-2's surrogates are the answer but introduce surrogate-drift risk. *Severity: medium.*
7. **The copilot is a chokepoint.** Grammar-constrained parsing buys safety at the cost of expressivity; analysts will ask questions the grammar cannot hold, and the pressure to "just let the LLM answer" will be constant and must be resisted institutionally, not just technically. *Severity: medium, perpetual.*
8. **Dual-use gravity.** A system that finds destabilization pathways for defense can be pointed outward. Enclaves and oversight mitigate access, not intent. This blueprint's legitimacy rests on the governance appendix being real. *Severity: structural.*

## 28. Second-Generation Architecture (Gen-2): the Amortized, Self-Extending Twin

Gen-2 keeps the Gen-1 skeleton and replaces its three slowest joints:

- **G2.1 Neural mechanism surrogates everywhere (B6 matured).** Every mechanism and the Tier-M field dynamics get conditional neural surrogates with *certified* fidelity envelopes (surrogate error bounds estimated by held-out simulation and embedded into the adversarial ball — model error and parameter error share one robustness budget). Result: interactive national counterfactuals, gradient-based policy search, real-time band recomputation during crises.
- **G2.2 NMC as the primary mechanism author (B5 matured).** Human experts move from writing mechanisms to *adjudicating* compiler proposals; the id-status ledger becomes the human–machine contract. The system begins extending its own causal vocabulary — measured by "mechanisms authored by NMC that survived 12 months of scoring."
- **G2.3 Crisis mode.** A fast path: pre-computed scenario libraries + surrogates + cached bands, refreshed continuously, so the first 72 hours of a crisis run on warm state (the Gen-1 cold-start critique #6).
- **G2.4 Cross-enclave federated mechanisms.** θ-posterior federation across allied/regional instances without raw-data sharing (mechanism-level diplomacy: shareable causal knowledge as a strategic asset class).
- **G2.5 Adversarial ecology v1.** The red team's attackers become *resident agents* inside evaluation: every nightly build is attacked automatically; robustness metrics become time series watched like uptime.

Gen-2 exit test: a counterfactual answer of national scope in <5 seconds, carrying a band whose certified surrogate error is part of the band.

## 29. Third-Generation Architecture (Gen-3): the World-Model Ecology — the publication-grade breakthrough

**Thesis.** Stop building *a* world model. Build an **ecology of competing, heterogeneous world models** whose population dynamics are governed by proper scoring rules — natural selection on calibration — with three scientific leaps:

- **G3.1 — Causal Foundation Model (CFM).** Pretrain a single sequence-to-structure model on *millions of resolved (evidence-window → SCM-delta → outcome) triples* across all domains and the synthetic COUNTERFACT-GEO families: a foundation model whose native output is *mechanism*, not text. RETRO-CAST/POLICY-TRACE become its pretraining corpus; NMC (B5) is its supervised ancestor. Hypothesis to test (falsifiable): mechanism-level transfer — a CFM trained on economics+climate questions improves zero-shot *conflict* forecasting via shared causal motifs (pass-through, capacity collapse, contagion), in a way no event-level model can. **Venue: NeurIPS/Nature Human Behaviour.**
- **G3.2 — Scoring-rule market over models.** Ensemble weights become a continuous *prediction-market mechanism* among model species (twins, surrogates, statistical, judgmental, CFM-instances): each stakes calibration capital, payouts by strictly proper rules, insolvency = retirement. Theoretical contribution: conditions under which such a market implements robust Bayesian aggregation with adversarial participants (bridges scoring-rule theory, market microstructure, and DRO). **Venue: NeurIPS/AAAI (theory + system).**
- **G3.3 — Governed performativity.** Full treatment of forecasting-as-intervention: fixed-point forecasts (B7) extended to *equilibrium selection with a governance constraint* — the system computes the set of self-fulfilling equilibria reachable by announcement policy and hands the *choice* to accountable humans with quantified consequences (steering portfolios). First formal separation of epistemic and steering authority in deployed forecasting. **Venue: Science Advances/Nature HB (with a normative-theory companion).**
- **G3.4 — Mechanism interlingua.** A typed, versioned exchange format for causal knowledge (mechanism cards with id-status, score history, jurisdiction tags) intended as an international standard — the TCP/IP of strategic foresight; enables allied federation and academic replication. **Venue: IEEE (standards track) + open consortium.**

**Why this is a genuine breakthrough and not scale-up:** Gen-3 changes the unit of machine knowledge from *predictions* (Gen-0/1) and *amortized simulators* (Gen-2) to **a self-renewing population of scored causal theories**. The system's output is no longer "70% [55–82]" but a living, auditable argument among models — with selection pressure supplied by reality and steering authority held by humans. Each of G3.1–G3.4 is independently publishable; together they constitute the program's claim on the field.

---

# Appendix A — Governance, Ethics, and Misuse Boundaries

Hard boundaries (architecture-enforced, not policy-aspirational): no individual-level profiling or targeting — minimum analytic unit is the H3 cell / population segment; information-domain tooling is detection/characterization only — no influence-conduct capability is built, and narrative-propagation simulators are gated to defensive studies with dual sign-off; harm-functional weights, performative announcements, and recommendation exports require signed human authority (separation of epistemic and decision power, §15.7, G3.3); independent oversight body with unredacted red-team access and publication rights for the OPEN enclave; civil-liberties impact assessment as a release gate alongside security gates; sunset-and-review statute recommended: the system's mandate expires and must be re-justified on a fixed cycle.

# Appendix B — Prototype Traceability Matrix

| Blueprint component | `cassandra-core` artifact |
|---|---|
| §4 Twin (Tier-S + macro core) | `core/engine.py` |
| §5 mechanism params + E2E training (B1) | `novelty/cassandra.py::CalibrationTrainer` |
| §15.3 bands (B3) | `Adversary` |
| §15.4 conformal (B4) | `ConformalLayer` |
| §10 policy engine | `InterventionSearch` |
| §6 analogs | `data/situation.json` analogs |
| §9 XAI objects | `core/phases.py::explain_forecast` |
| §7 scenario discovery | `ScenarioEngine` |
| §24 quantitative red team (seed) | `red_team_summary` + bands |
| §19 dashboard (analyst persona seed) | `output/dashboard.html` |
| §16 leakage firewall (seed) | replay-window protocol in `engine.py` |
| §26 Phase-0 exit | `tests/test_smoke.py` — 14/14 |

*End of blueprint. The research paper formalizing B1–B8 and the Gen-3 program is the designated next deliverable.*
