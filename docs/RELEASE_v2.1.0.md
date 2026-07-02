# Release v2.1.0 — Phase 3 (partial)

**Date:** 2026-06-28 · **Scope:** build-plan tasks 74–94 · **Changelog:** `CHANGELOG.md`
**Theme:** *Multi-tenant, Observable, Scaled* — auth + clearance, the LLM/faithfulness
layer, deploy/observability, scale, and pilot/ops hardening on top of the v2.0.0 core.

## Highlights
- **Access & data protection:** OIDC/JWT gateway with clearance claims (74), cell-level
  clearance redaction (75), DLP export gates (91), dual-control θ promotion with a
  tamper-evident audit chain (89).
- **LLM & faithfulness:** OpenAI-compatible vLLM NLU assist (76), deterministic
  sentence→object entailment gate (77).
- **Deploy & observability:** Helm chart (78), Prometheus RED metrics + Grafana board (79),
  structured JSON logging + request-id tracing (80), SLO-burn alert rules with promtool
  synthetic-breach tests (81), DR active-active with PG streaming replication (90).
- **Scale:** engine sharding (82), full-fidelity nightly band cache (83), B6 surrogate spike
  (84), counterfactual cache (85).
- **Pilot & analytic integrity:** pilot onboarding kit (86), dissent/right-of-reply (87),
  quarterly red-team exercise #1 (88), 50-cartridge case library + learned analog metric
  (92, 93), frozen-baseline ratchet regression gate (94).

## Exit gates (all green)
`scripts/cut_release.sh --check` runs: engine smoke, full suite (189 passed / 1 PG-skip),
latency SLO gate, NLU-assist p95 gate, red-team gates (θ-ball / ablation / injection +
exercise #1), NLU contamination gate, ratchet regression gate, and OpenAPI drift.
CI additionally runs test-pg, frontend, loadtest, helm, alerts (promtool), and openapi.

## Cutting the tag
`VERSION` (2.1.0) is the single source of truth (read by the API and embedded in
`docs/openapi/openapi.json`). The working tree is not yet under version control; to tag:

```bash
scripts/cut_release.sh            # runs every gate, then tags v2.1.0 if a git repo
# or manually:
git add -A && git commit -m "ARGUS v2.1.0 — Phase 3 (partial), tasks 74–94"
git tag -a v2.1.0 -m "ARGUS v2.1.0 — Phase 3 (partial)"
```

## Next
Phase-3 tail — tasks 95–100 (accreditation pack, retro backfill, watch rota, perf/cost
freeze, change-control freeze, production go-live → v3.0.0).
