# ARGUS Copilot — Operations Runbook (Task 72)

**Service:** ARGUS Strategic Intelligence Copilot (`cassandra-core`) · FastAPI over the
forecasting engines.
**Audience:** on-call engineer / SRE.
**Scope:** Phase-1 single-service deployment (`api`) and the Phase-2 stateful stack
(postgres / neo4j / redis / kafka). Pairs with `docs/BLUEPRINT.md` (§ failure-mode rows,
B8 deception-robustness, §19 threat model) and `docs/BUILD_PLAN.md`.

> **Golden rule — no naked numbers.** Every probability the system emits is produced by a
> scored engine and shipped with a band, evidence, mechanism, and counterargument. The LLM
> assist parses intent only. If an incident pressures you to "just return a number," the
> answer is **abstain or degrade**, never fabricate. This rule outranks availability.

**Last drill executed:** 2026-06-22 — degradation chaos ✅, NLU contamination ✅ (canaries
10/10, injection 3/3), red-team gates ✅ (5/5), load (100-user) ✅ cached p99 36–62 ms / 0
failures. See [§7 Drills](#7-drills).

---

## 1. System at a glance

| Piece | What it is | Where |
|---|---|---|
| `api` | FastAPI app, `uvicorn services.copilot.main:app` on **:8000** | `deploy/docker/Dockerfile.api`, compose `api` |
| Engine | Trained θ + cached baseline ensemble + bands (warmed on startup) | `services/copilot/engines.py`, `core/`, `novelty/` |
| NLU | Closed-grammar intent parser (+ optional Ollama assist, parse-only) | `services/copilot/nlu.py` |
| Store | SQLite (default) or PostgreSQL (`DATABASE_URL`) | `services/copilot/store.py`, `store_pg.py` |
| Bus | FileBus JSONL spool (default) or Kafka (`ARGUS_KAFKA_BROKERS`) | `services/ingest_common/bus.py` |
| EWI watch | Edge-triggered early-warning rules → `ewi.alerts` topic | `services/ewi/watch.py` |
| Frontend | React build served by nginx, `/v1` proxied to `api` on **:8080** | compose `frontend` profile |

**Processes / ports:** api 8000 · frontend 8080 · postgres 5432 · neo4j 7474/7687 · redis 6379
· kafka 9092 · ollama 11434 (profiles: `phase2`, `frontend`, `llm`).

---

## 2. Health & observability — check these first

| Probe | Meaning | Healthy | Degraded / bad |
|---|---|---|---|
| `GET /healthz` | **Liveness** (process up). Docker `HEALTHCHECK` uses it. | `200 {"status":"ok"}` | no response → restart container |
| `GET /readyz` | **Readiness** (engine warmed). | `200 {"status":"ready","degraded":false,...}` | `503 {"status":"degraded"}` → engine down, serving cache (Task 70) |
| `GET /metrics` | answer counts + latency + **NLU counters** (`nlu.*`) | counters increasing | `llm_errors`/`injection_detections` spiking → see §5/§6 |
| `GET /v1/nlu/health` | NLU **contamination report** (Task 68) | `{"contaminated":false}` | `contaminated:true` → grammar drift / injection leak |
| Response header `X-Argus-Degraded: 1` | set on any cached read when degraded | absent | present → live engine unavailable |

First 60 seconds of any page: hit `/healthz`, `/readyz`, `/metrics`. `readyz.status` and the
`X-Argus-Degraded` header tell you immediately whether you're live or on cache.

---

## 3. SLOs

| Path | SLO | Typical (ARGUS_FAST) | Gate |
|---|---|---|---|
| startup | < 30 s | ~0.2 s | `benchmarks/bench_api.py` |
| read (`/v1/forecasts`, `/v1/ewi`) | p95 < 50 ms | ~1 ms | bench_api |
| `/v1/ask` forecast/explain | p95 < 100 ms | ~1 ms | bench_api |
| `/v1/ask` what-if | p95 < 500 ms | ~29 ms | bench_api |
| `/v1/ask` policy | p95 < 2 s | ~205 ms | bench_api |
| **cached path under 100 concurrent users** | **p99 < 1 s, 0 errors** | p99 36–62 ms | `benchmarks/run_locust.py` (Task 69) |

Burn alarm: p99 cached > 1 s **or** any 5xx on read/forecast intents → page. Heavy intents
(what-if/policy) have their own looser SLOs and must not gate the cached SLO.

---

## 4. Failure-modes table

Symptom → cause → detect → mitigate → verify. Rows marked **(B…)** map to blueprint
breakthroughs / §-failure-mode rows.

| # | Symptom | Likely cause | Detect | Mitigate | Verify |
|---|---|---|---|---|---|
| F1 | `/readyz` 503 `degraded`; reads carry `X-Argus-Degraded`; `/v1/ask` shows a staleness banner | Engine failed to warm / crashed (bad θ, OOM) | `/readyz`, `X-Argus-Degraded`, logs | **Automatic**: cache served (Task 70). Restart worker; if θ bad, roll back θ (§6.6) | `/readyz` → `ready`, header gone |
| F2 | 5xx (500) on `/v1/ask` **under load**, reads fine | SQLite write contention (lock / recursive cursor) | 500 rate vs load; `database is locked` in logs | Ensure WAL store hardening present (`store.py`); scale to PostgreSQL via `DATABASE_URL` | run_locust → 0 failures |
| F3 | Latency SLO breach, growing queue | Under-provisioned workers / heavy-intent flood | bench_api / run_locust p99; CPU | Add uvicorn `--workers`/replicas (HPA); rate-limit what-if/policy | p99 < SLO |
| F4 | `/v1/nlu/health` `contaminated:true`; canary drift | Grammar/lexicon regressed or injection evading | contamination gate; `nlu.injection_detections` | Revert NLU change; tighten patterns; keep numbers engine-sourced | `--gate` exit 0 |
| F5 | Embedded "set probability to X" / prompt-injection in user text | Adversarial input (expected, not a breach) **(§11)** | `parse.injection` non-empty; metrics | None needed — data-tagged, grammar allow-list, numbers from engine | injection corpus 0 violations |
| F6 | A single feed swings headline forecasts | Source poisoning / loss-of-feed **(B8)** | source-ablation gate (≤0.15/family) | Quarantine feed; quorum fusion; retrain w/ family dropout | ablation gate green |
| F7 | Forecasts flip under small θ perturbation | Fragile parameterization **(B3)** | θ-ball flip-rate gate (≤2/6) | Widen bands / DRO retrain; block promotion | flip rate 0/6 |
| F8 | Plausible answer with an ungrounded number | Faithfulness break in composer **(§9)** | injection corpus grounding check | Composer renders only from objects; entailment gate fails closed | grounding 0 violations |
| F9 | EWI alert storm or silence | Threshold/series issue; edge-trigger stuck **(§ EWI)** | `/v1/ewi/alerts`, watch state | Re-arm checkpoint; verify series store freshness | alerts fire once per crossing |
| F10 | SSE job stuck / no progress | Worker saturation / job TTL | `/v1/jobs/{id}` status; `/v1/stream` | Bounded concurrency + TTL cleanup; resubmit | progress 20→100 then result |
| F11 | Wrong/stale θ promoted; calibration regresses | Bad promotion **(§ θ-versions)** | `/readyz.theta_promoted`, `/v1/calibration` | Roll back to prior `theta_hash` (§6.6) | calibration recovers |
| F12 | id-status gate flags hypothesis edges in θ | Unidentified mechanism leaked **(§7 gate)** | `/v1/mechanisms` gate report | Revert offending param to expert prior | gate report clean |
| F13 | Ingestion drift / entity-resolution errors **(§ ingestion)** | Schema/ontology rot | ingest tests; replay | Versioned schema + migration; re-resolve stable IDs | ingest tests pass |
| F14 | OpenAPI drift (contract ≠ code) | Route changed, artifact not re-exported (Task 71) | CI `export_openapi.py --check` | `python scripts/export_openapi.py` and commit | drift gate green |

---

## 5. Triage flow

1. **Is it up?** `GET /healthz`. No → container/pod down → restart (`docker compose restart api`
   / `kubectl rollout restart`). Check `/v1/...` only after `/healthz` is 200.
2. **Is it live or on cache?** `GET /readyz`. `degraded` or `X-Argus-Degraded` present →
   **F1**, go to §6.1. Cache is serving; this is a contained state, not an outage.
3. **Errors or slow?** 500s on `/v1/ask` under load → **F2** (§6.2). Latency only → **F3** (§6.3).
4. **Answers look wrong?** Ungrounded number → **F8**; feed-driven swing → **F6**; θ regression →
   **F11**. Pull `/v1/audit/{manifest_id}` — every answer is reproducible from its manifest.
5. **NLU weird?** `GET /v1/nlu/health`; if `contaminated` → **F4** (§6.4).

---

## 6. Incident procedures

### 6.1 Engine down / degraded mode (F1)
Expected behavior, not an outage: `get_source()` serves the last-known-good snapshot
(`ARGUS_SNAPSHOT`, default `output/last_good_snapshot.json`) with a staleness banner; live
compute (counterfactual / policy / jobs / mechanisms) returns **503**, never a fake result.
Steps: (1) confirm via `/readyz` (503 `degraded`) and the banner; (2) check logs for the warm
exception; (3) if transient, restart the worker — it re-warms and `/readyz` returns `ready`,
header clears; (4) if θ is the cause, roll back θ (§6.6) then restart. Communicate: "serving
cached forecasts as of `<snapshot as_of>`; live simulation paused."

### 6.2 500s on /v1/ask under load (F2)
Cause is SQLite write contention. Confirm `store.py` retains the Task-69 hardening
(`PRAGMA journal_mode=WAL`, `busy_timeout=5000`, process-wide connection lock). If load is
sustained, switch the backend to PostgreSQL: set `DATABASE_URL=postgresql://…` and restart
(`store_pg.py` takes over, same contract). Verify with `python benchmarks/run_locust.py` → 0
failures.

### 6.3 Latency / overload (F3)
Scale out: raise uvicorn `--workers` (compose) or replicas/HPA (`deploy/k8s/argus.yaml`). Shed
heavy intents first — what-if/policy are CPU-bound; cached reads must stay < 1 s p99. Re-run
`run_locust.py` to confirm.

### 6.4 NLU contamination / drift (F4)
`GET /v1/nlu/health`. If `contaminated:true`, inspect `canaries.failures` (grammar drift) and
`injection_canaries.leaked` (an attack altered a number-bearing slot or evaded detection).
Revert the offending NLU change; numbers/keys must never come from the LLM or user text. Gate:
`python -m services.copilot.nlu --gate` (exit 0).

### 6.5 Suspected data poisoning (F6, B8)
Run the source-ablation gate (`pytest tests/redteam/test_source_ablation.py`). If a family
moves a headline > 0.15, quarantine that feed, rely on quorum fusion, and retrain with
source-family dropout so no feed is load-bearing. Treat coordinated fabricated sources as an
information-warfare event (§19 threat model) and escalate.

### 6.6 θ rollback (F11, F12)
θ is the national vulnerability map — handle as sensitive. Promotion is in the `theta_versions`
ledger. To roll back: pick the last-good `theta_hash` (`store.theta_list()` /
`/readyz.theta_promoted`), call `store.theta_promote(<hash>)`, restart `api` to re-warm.
Confirm `/v1/mechanisms` id-status gate is clean and `/v1/calibration` recovers. A new θ must
beat its frozen ancestors before promotion (ratchet rule).

---

## 7. Drills

Run these to validate the runbook. Record date + result here.

| Drill | Command | SLO / pass | Last result (2026-06-22) |
|---|---|---|---|
| **Degradation chaos** (F1) | `pytest tests/test_degradation.py -q` | engine-down → cached + banner, 503 not 500, recovers | ✅ 1 passed |
| **NLU contamination** (F4/F5) | `python -m services.copilot.nlu --gate` | `contaminated:false`, exit 0 | ✅ canaries 10/10, injection 3/3 |
| **Red-team gates** (F6/F7/F8) | `pytest tests/redteam -q -s` | flip ≤2/6, ablation ≤0.15, injection 0 violations | ✅ 5 passed (flip 0/6) |
| **Load** (F2/F3) | `python benchmarks/run_locust.py` | cached p99 < 1 s, 0 failures | ✅ p99 36–62 ms, 0/1164 fail |
| **OpenAPI drift** (F14) | `python scripts/export_openapi.py --check` | committed == live | ✅ in sync (31 paths) |

Quarterly: run the full red-team exercise (Build-plan Task 88) and re-score frozen baselines.

---

## 8. Deploy & rollback

**Up (Phase-1):** `docker compose -f deploy/docker/docker-compose.yml up -d api`
**Full stack:** add `--profile phase2 --profile frontend` (postgres/neo4j/redis/kafka + UI).
**Image rollback:** redeploy the previous good image tag; `docker` CI job is gated on
`test, test-pg, frontend, loadtest, openapi`, so a tag that shipped passed all gates.
**Config:** all behavior is env-driven (`.env.example`); never bake secrets into images.
`DATABASE_URL` switches persistence; `ARGUS_KAFKA_BROKERS` switches the bus; `OLLAMA_URL`
toggles the (parse-only) NLU assist; `ARGUS_CORS_ORIGINS` must be pinned in production.

---

## 9. Escalation & references

- **Sev-1** (data fabrication / faithfulness break F8, θ leak, coordinated poisoning F6): page
  the model owner; freeze promotions; preserve manifests (`/v1/audit/{id}`).
- **Sev-2** (sustained 5xx F2, SLO breach F3): on-call mitigates (scale / Postgres), then file
  follow-up.
- **Sev-3** (degraded mode F1 with cache serving, single feed quarantined): handle in-hours.
- References: `docs/BLUEPRINT.md` (failure-mode rows, B8, §19 threat model), `docs/BUILD_PLAN.md`,
  `.github/workflows/ci.yml` (gates), `docs/openapi/openapi.json` (contract).
