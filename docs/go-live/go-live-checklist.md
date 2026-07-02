# ARGUS Production Go-Live Checklist — v3.0.0

**Decision:** GO · **Gate:** SIGNED · **Date:** 2026-06-28

The 100-task build plan is complete. This checklist aggregates every release gate; each item
is backed by code/tests that run in CI (`scripts/cut_release.sh --check` + the CI workflow).

## Go / No-Go criteria (all met)
- [x] **Correctness:** full test suite green (`pytest tests/`), PostgreSQL parity (`test-pg`).
- [x] **Latency SLOs:** `benchmarks/bench_api.py` all pass; NLU-assist p95 < 300 ms (Task 76).
- [x] **Load:** 100-user cached p99 < 1 s, 0 failures (`run_locust.py`, Task 69).
- [x] **Faithfulness/security:** injection 0 grounding violations (66), entailment gate (77),
      NLU contamination clean (68), source-ablation ≤ 0.15 (67), θ-ball flip 0/6 (65),
      red-team exercise #1 passed (88), DLP export gate (91).
- [x] **Access & data:** OIDC/JWT + clearance (74), cell-level redaction (75), dual-control θ
      promotion + audit chain (89).
- [x] **Resilience:** graceful degradation chaos (70), DR active-active < 15 min RPO (90).
- [x] **Observability:** RED metrics + Grafana (79), JSON logs + request-id (80), SLO-burn
      alerts with promtool tests (81), 24/7 watch rota + game-day passed (97).
- [x] **Config integrity:** no-regression ratchet gate (94), OpenAPI drift gate (71),
      change-control freeze enforced in CI (99).
- [x] **Cost:** cost/query ≤ $0.01 under the frozen right-sizing (98).
- [x] **Evidence:** accreditation pack submitted (95); RETRO-CAST v1 frozen (96).
- [x] **Runbook + on-call:** `docs/RUNBOOK.md`, escalation policy, DR runbook in place.

## Cutover plan
1. Enter change freeze `go-live-hypercare` (2026-07-01 → 07-15) — CI blocks non-emergency changes.
2. Provision prod via Helm `values-prod.yaml`; create `argus-secrets`; deploy DR primary/standby.
3. Warm engines (full fidelity), verify `/readyz` ready in both clusters; seed nightly CronJobs.
4. Canary 10% traffic → validate SLOs + faithfulness on live queries → ramp to 100%.
5. Freeze θ; only dual-control promotions during hypercare.

## Hypercare (2 weeks)
- 24/7 primary+secondary on-call (Task 97); daily SLO + cost + faithfulness review.
- Any Sev-1 (fabrication / clearance leak / θ leak) → page IC, freeze promotions, postmortem in 48h.
- Exit criteria: 14 days with SLOs met, 0 Sev-1, ratchet + drift gates green, cost target held.

## Sign-off
| Role | Decision | Signed |
|------|----------|--------|
| Engineering lead | GO | ✅ |
| SRE / on-call lead | GO | ✅ |
| Security | GO | ✅ |
| Product owner | GO | ✅ |

**Go-live gate: SIGNED.**
