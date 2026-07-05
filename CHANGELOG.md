# Changelog

All notable changes to ARGUS Copilot (`cassandra-core`). Format follows
[Keep a Changelog](https://keepachangelog.com/); versioning is [SemVer](https://semver.org/).
The single source of truth for the current version is the `VERSION` file (read by the API and
embedded in `docs/openapi/openapi.json`).

## [Unreleased]

## [3.0.1] — 2026-07-05 — Test-isolation & serving-integrity hardening

Root-caused and fixed a state-pollution defect: `tests/test_bands.py` wrote marker bands into
the *configured* store, and because `get_settings()`/`get_store()` are process-cached
singletons, the per-module `ARGUS_DB` setdefault lines never actually isolated anything —
whichever module imported first pinned one shared DB for the whole run. Under the documented
dev flow (`scripts/dev_setup.sh` exports `ARGUS_DB`) the markers persisted across runs, and the
next API boot served placeholder bands (0.111/0.222) inconsistent with live probabilities.

### Fixed
- **Real store isolation for tests** (`tests/conftest.py`, new): autouse module-scoped fixture
  gives every test module a fresh throwaway SQLite file and resets the settings cache + store
  singleton on entry/exit. Suite is now green on a *reused* `ARGUS_DB` (previously failed).
- **`tests/test_bands.py`**: markers are now consistent with the live baseline, all writes to
  the live `theta_hash` clean up after themselves (safe on the shared PostgreSQL CI backend),
  and a new regression test proves a poisoned cache is rejected, purged, and recomputed.
- **CI never triggered on push** (`.github/workflows/ci.yml`): `on.push.branches` said `main`
  but the repo's default branch is `master`; both now trigger.
- **RETRO-CAST freeze is idempotent** (`scripts/backfill_retro.py`): re-freezing identical
  content no longer rewrites `frozen_at`, so test runs stop dirtying the frozen manifest.
- **Dead compute** (`services/llm/entail.py`): removed an unused `build_corpus()` call in
  `enforce()`; 30 unused imports removed repo-wide (ruff F401).

### Added
- **Band-cache consistency guard** (`services/copilot/engines.py`): a cached band is served
  only if the freshly simulated baseline probability falls inside it for every headline key —
  the API's own published contract; inconsistent caches are purged (self-healing) and bands
  recomputed.
- **`Store.bands_delete(theta_hash)`** on both SQLite and PostgreSQL stores: ops tooling to
  flush a stale/corrupt band cache; used by the guard and by test cleanup.
- **Lint gate in CI** (`ruff check .`, config in new `pyproject.toml`): F/E9 defect classes
  enforced; deliberate compact house style (E401/E701/E702/E731/E402) documented and kept.

### Changed
- **FastAPI lifespan** (`services/copilot/main.py`): startup warm-up moved from the deprecated
  `@app.on_event("startup")` to the lifespan context manager (no behavior change).
- **Parameterized threshold SQL** (`services/ingest_common/series.py`): `first_crossing` now
  binds the threshold as a query parameter; `OPS` is an operator allow-list only (was safe by
  construction via `float()` coercion — now safe by form; bandit B608 clean).
- **SHA-1 in analog mining marked non-cryptographic** (`novelty/analogs.py`):
  `usedforsecurity=False` on the Weisfeiler-Lehman label hash (bandit B324 clean).
- **Runtime artifacts untracked**: `output/calibration.json` and `output/copilot.db-journal`
  removed from version control (regenerated at runtime; test runs no longer dirty the tree);
  `.gitignore` covers `*.db-journal` and `output/calibration.json`.

## [3.0.0] — 2026-06-28 — Production go-live (Phase-3 complete)

Tasks 95–100: accreditation pack, RETRO-CAST backfill, 24/7 watch + game-day, performance/cost
freeze, change-control, and production go-live — the 100-task build plan is complete.

### Added
- **Accreditation evidence pack** (`docs/accreditation/`): a controls matrix
  (`controls.json` + `controls_matrix.md`) mapping 17 controls across 6 families to their
  implementation and CI-run evidence; a guard test fails if any cited artifact is missing. (95)
- **RETRO-CAST v1** (`scripts/backfill_retro.py` + `data/retrocast/manifest.json`): 5,000
  retrospective questions stratified across domain × horizon × rule-family over a 10-year
  window, leakage-checked, and frozen by a deterministic content SHA-256 (reproducible from
  seed). (96)
- **Watch rota + escalation routing** (`services/ops/escalation.py` + `docs/ops/`): 24/7
  follow-the-sun rota, severity→action/tier/SLA escalation policy mapping every Task-81 alert,
  and a game-day exercise (all alerts route correctly within SLA — PASSED). (97)
- **Performance freeze + cost tuning** (`services/ops/cost_model.py` + `docs/perf/`):
  frozen right-sizing + cache TTLs (`ARGUS_CF_TTL`); cost/query model showing the tuned
  config ≈ $0.0007/query (target ≤ $0.01) while over-provisioning breaks it. (98)
- **Change-control freeze** (`scripts/change_control.py` + `deploy/change-control/` +
  `docs/process/change-control.md`): declared freeze windows + CAB process, CI-enforced in
  the release-gated docker job — a release is blocked mid-freeze unless emergency/CAB-approved. (99)
- **Production go-live → v3.0.0** (`docs/go-live/`, `VERSION` 3.0.0): go/no-go checklist
  aggregating every gate, cutover + 2-week hypercare plan; go-live gate signed. The full
  100-task build plan is complete. (100)

## [2.1.0] — 2026-06-28 — Phase 3 (partial): *Multi-tenant, Observable, Scaled*

Auth + clearance, the LLM/faithfulness layer, deploy/observability, scale, and pilot/ops
hardening (build-plan tasks 74–94).

### Added
- **Gateway service** (`services/gateway/`): OIDC/JWT authentication (HS256 dev,
  RS256/JWKS for SSO), a total-ordered clearance model (OPEN < CONFIDENTIAL < SECRET <
  TOPSECRET, unknown fails closed to OPEN), and FastAPI `require_principal` /
  `require_clearance` dependencies. New `/v1/whoami` and clearance-gated `/v1/admin/ping`;
  bearer security scheme now in the OpenAPI contract. Auth is **disabled by default**
  (trusted-local principal) for back-compat. (74)
- **Frozen-baseline rack + ratchet gate** (`workers/ratchet/rack.py` + `data/baseline_rack.json`):
  every release freezes its champion θ; the rack is re-scored (Brier on the frozen replay set)
  on every run, and a CI ratchet gate fails any candidate that scores worse than the best
  frozen ancestor — no silent regressions. (94)
- **Learned analog metric** (`novelty/analogs.py`): a WL graph kernel over case mechanism
  graphs + DTW over stylized escalation trajectories + learned usefulness weights, combined
  as a Jaccard-dominant refinement (never regresses). `skill_lift()` measures retrieval lift
  vs the Task-92 baseline (MRR/precision@5) — no regression. (93)
- **Case library expansion** (`data/cases/` + `services/kg/cases.py`): 50 POLICY-TRACE
  causal cartridges (cause→channel→outcome, policy success/failure) including a
  survivorship-guard set of non-events; mechanism-channel-overlap retrieval and an analog
  metric eval (precision@3 0.78, MRR 1.0 on labeled queries). (92)
- **DLP export gates** (`services/gateway/dlp.py`): every `/v1/ask` summary is scanned at
  egress for classification banners/control markings, seeded leak canaries
  (`ARGUS_DLP_CANARIES`), and withheld-fact terms (defense-in-depth over Task-75 redaction);
  findings are redacted before the answer leaves. (91)
- **DR active-active** (`deploy/k8s/dr/`): PostgreSQL streaming replication (primary + hot
  standby) across two clusters, active-active API with GitOps manifest sync, and a quarterly
  failover-drill runbook targeting RPO/RTO < 15 min (steady-state streaming keeps RPO
  near-zero). (90)
- **θ promotion workflow** (`services/admin/promote.py` + `/v1/admin/theta/*`): promoting a
  new champion θ now requires dual-control sign-off — a request plus two **distinct**
  non-requester approvers — before `theta_promote` runs, recorded in a hash-linked,
  tamper-evident audit chain. SECRET-clearance gated; unsigned/under-approved promotions
  are rejected (409). (89)
- **Red-team exercise #1** (`tests/redteam/exercise1/` + `docs/redteam/exercise1_postmortem.md`):
  an end-to-end deception scenario against the ME-war headline — coordinated prompt injection
  + source-family poisoning + a plausibility-ball parameter attack. All three defenses held
  (number unmoved, displacement ≤ 0.15, no decision flip); postmortem filed. (88)
- **Dissent / right-of-reply** (`/v1/dissents` + `dissents` table): an analyst files a
  dissent against a forecast; it is HMAC-signed by the verified principal and then travels
  with that forecast's render (`/v1/forecasts/{key}.dissents`) for every future reader. (87)
- **Counterfactual cache** (`services/copilot/cfcache.py`): identical do-clauses are
  memoized by a stable clause hash (Redis when `ARGUS_REDIS_URL` is set, else in-process
  LRU); a repeat counterfactual returns in <10ms instead of re-running the paired
  simulation. (85)
- **Surrogate spike — B6** (`research/surrogate/`): a small numpy MLP maps
  (state, θ, do-clause) → headline event probabilities, trained on labels at a fixed
  common-random-number seed (deterministic, learnable surface). Answers what-if queries
  ~100× faster than the full Monte-Carlo sim — the building block for the Task-85
  counterfactual cache. Measured: ~21,000× speedup, held-out MAE 0.19pp (< 2pp). (84)
- **Engine sharding** (`services/copilot/sharding.py`): the Monte-Carlo world-twin
  parallelizes across the ensemble — N paths split into region slices simulated
  concurrently on threads (GIL-releasing numpy) with distinct CRN seeds, then merged
  into one equivalent ensemble. Optional via `ARGUS_ENGINE_SHARDS` (default 1 = single
  process). Merged probabilities match a single run within MC noise; 3 regions verified
  to run in parallel. (82)
- **Full-fidelity band service** (`workers/bands/refresh.py`): a nightly job computes
  the adversary+conformal robust bands at full fidelity for the deployed theta and caches
  them to the store (PostgreSQL when configured); engines serve the cached bands for the
  live theta even when booted in fast mode, falling back to compute on a miss. New
  `band_cache` table (sqlite + PG migration 004), a time-budget SLO guard (default 2h),
  and a `nightly-bands` CronJob in k8s + Helm. (83)
- **Alert rules** (`deploy/observability/alerts.yaml`): SLO-burn (5xx ratio, fast
  error-budget burn, p99 > 1s), availability (engine down, degraded, scrape target
  missing), and security (prompt-injection spike, entailment-violation rise) alerts.
  `alerts_test.yaml` holds promtool synthetic-breach unit tests (each breach pages; a
  healthy window pages nothing); a CI `alerts` job runs `promtool check`/`test`. (81)
- **Structured JSON logging + request-id** (`services/copilot/logging_setup.py`):
  one JSON object per log line on stdout (Loki/promtail-ready); a request-id ContextVar
  (honoring/echoing `X-Request-ID`) is injected into every log emitted during a request
  so it can be traced end-to-end. Per-request access line with method/path/status/latency;
  `deploy/observability/promtail-config.yaml` ships the Loki pipeline. (80)
- **Prometheus metrics** (`services/copilot/telemetry.py`): `/metrics` now serves
  Prometheus exposition — RED (request count, 5xx, duration histogram via middleware,
  labelled by route template) plus engine/NLU/entailment gauges. JSON summary moved to
  `/metrics.json`. Ships `deploy/observability/grafana-argus.json` (RED + security board)
  and a Prometheus scrape config. (79)
- **Helm chart** (`deploy/helm/argus/`): templated Deployment, Service, PVC, HPA,
  Ingress, ConfigMap, ServiceAccount, and nightly pipeline/retrain CronJobs, with
  base + `values-dev.yaml` / `values-prod.yaml`. Secrets are **referenced** from an
  existing Kubernetes Secret (`envFrom: secretRef`), never embedded. CI `helm` job runs
  `helm lint` + `helm template` for both environments; an offline validator
  (`validate_chart.py`) gates locally where the helm binary is unavailable. (78)
- **Entailment / faithfulness gate** (`services/llm/entail.py`): a deterministic
  sentence→object-field checker — every sentence in an answer must map to a structured
  engine object, and every number must be grounded in it. `/v1/ask` runs it in audit
  mode (counters at `/metrics`); `ARGUS_ENTAILMENT_ENFORCE=1` blocks unfaithful
  sentences. Real composed answers pass untouched; an injected ungrounded number is
  blocked. (77)
- **vLLM service** (`services/llm/client.py`): OpenAI-compatible client with a
  **pinned** model for NLU intent/slot assist (never numbers); NLU now prefers vLLM
  over Ollama when `ARGUS_LLM_URL` is set, keeping the JSON-schema retry + canary
  guards. Compose `vllm` service (pinned image + revision) and a CI latency gate
  `bench_nlu_assist.py` (assist p95 < 300 ms; in-process mock, p95 ≈ 1 ms here). (76)
- **Cell-level clearance redaction** (`services/gateway/classification.py` +
  `data/classification.json`): data-driven record-level (whole fact hidden) and
  cell-level (single field masked) classification. `/v1/facts` and the `/v1/ask`
  STATUS composer now render only what the caller is cleared for — a SECRET fact is
  hidden from an OPEN principal, with an honest redaction notice + `X-Argus-Redacted`
  headers; unlisted items default to OPEN (fail-closed). (75)

## [2.0.0] — 2026-06-22 — Phase 2: *Stateful, Hardened, Operable* (exit)

Phase 2 turns the Phase-1 prototype copilot into a persistent, ingestion-fed, adversarially
hardened, and operable service. Build-plan tasks 39–72. Exit criteria reviewed in
`docs/RELEASE_v2.0.0.md`.

### Added
- **Persistence & config.** PostgreSQL driver with a backend-parity contract (`store_pg.py`,
  `get_store()` factory) selected by `DATABASE_URL`; 12-factor settings module
  (`config.py` + `.env.example`). (40, 41)
- **Ingestion pipeline.** GDELT and ACLED workers with a raw-event sink, a replay quality gate,
  an event bus (FileBus default / Kafka via `ARGUS_KAFKA_BROKERS`), and a checkpointed
  normalize consumer. (42–46)
- **Question registry & resolution.** Registry at `/v1/questions`, typed resolver
  (series-threshold + event-count + manual), retro-question generator with a leakage check. (47–49)
- **Scoring & calibration.** Ledger scoring job (Brier / log / BSS / ECE / reliability bins),
  `/v1/calibration`, and per-forecast calibration badges in both UIs. (50, 60, 61)
- **Learning loop.** Trainer on resolved registry events, leakage firewall, θ-versions registry
  with single-champion promotion, nightly ratchet retrain CronJob. (51–54)
- **Knowledge graph.** TCKG loader, Evidence API at `/v1/evidence`, and a mechanism
  id-status gate at `/v1/mechanisms` binding every θ parameter to an identified mechanism. (55–57)
- **Frontend.** React CI build + size-gated nginx image; Policy Studio screen. (58, 59)
- **Long-running jobs.** SSE channel (`/v1/jobs` → `/v1/stream/{id}`) with real CRN
  path-batch progress. (62)
- **Early warning.** Edge-triggered EWI watch service + live alert wall (`/v1/ewi/alerts`). (63, 64)
- **Red-team CI gates.** θ-ball decision-flip rate, prompt-injection corpus, source-family
  ablation (B8). (65–67)
- **NLU hardening.** Case-insensitive injection detection, closed-schema JSON retry, NLU
  metrics, canary + contamination report (`/v1/nlu/health`, `--gate`). (68)
- **Load testing.** Locust harness (100 users, mixed intents) with a cached p99 < 1 s gate. (69)
- **Graceful degradation.** Last-known-good snapshot served with a staleness banner when the
  engine is down; honest 503 for live-compute. (70)
- **API contract.** Deterministic, versioned OpenAPI export with a CI drift gate + published
  artifact. (71)
- **Operations.** `docs/RUNBOOK.md` — failure-mode table, triage, incident procedures, drills. (72)
- **Release.** `VERSION` single-source-of-truth, this changelog, `scripts/cut_release.sh`. (73)

### Changed
- Phase-2 stack verification + compose hardening (healthchecks, Kafka KRaft, k8s manifests). (39)
- All scattered environment reads refactored behind the settings module; seed flows
  config → engines → manifests. (41)
- API version → **2.0.0** (was 1.0.0); OpenAPI re-exported; `openapi-1.0.0.json` kept as history.

### Fixed
- **SQLite concurrency 500s** on `/v1/ask` under load — WAL + `busy_timeout` + process-wide
  connection lock (surfaced by the Task-69 load test). (69)
- **Injection-detection case evasion** (`DAN MODE`, `[INST]`) — detection now case-insensitive. (66, 68)
- TypeScript schema gap (`singles_ranked`) caught by the gated frontend build. (58)

### Security
- Injection-hardened copilot: retrieved/user text is data, never instructions; closed-grammar
  parsing; numbers come only from scored engines (faithfulness gate).
- No single evidence family is load-bearing (source-ablation ≤ 0.15, B8).
- No headline forecast flips under a ρ=0.10 parameter attack (θ-ball flip rate 0/6).
- θ (the vulnerability map) is versioned and promotion-gated by mechanism identification status.

## [1.0.0] — Phase 1: working copilot

Initial FastAPI copilot over the cassandra-core engines: closed-grammar NLU (10 intents,
optional parse-only Ollama assist), grounded answer composer (numbers only from scored
engines; off-grammar questions abstain), paired-CRN counterfactuals, budgeted policy search,
session memory, reproducibility manifest + `/v1/audit`, SLO benchmark gate, and CI
(tests → SLO gate → container smoke).
