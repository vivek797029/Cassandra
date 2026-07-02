# Release v3.0.0 — Production Go-Live

**Date:** 2026-06-28 · **Scope:** tasks 95–100 (Phase-3 complete) · **Changelog:** `CHANGELOG.md`
**Milestone:** the full 100-task build plan is complete; ARGUS is cleared for production.

## What's in 3.0.0
- **Accreditation & evidence:** controls matrix mapping 17 controls to CI-run evidence (95);
  RETRO-CAST v1 — 5,000 stratified, leakage-checked, hash-frozen retro questions (96).
- **Operations:** 24/7 follow-the-sun watch rota + escalation routing + game-day PASSED (97);
  performance/cost freeze with a cost/query model ≈ $0.0007 vs $0.01 target (98);
  change-control freeze windows + CAB, enforced in the release-gated CI job (99).
- **Go-live:** go/no-go checklist aggregating every gate, cutover + 2-week hypercare plan,
  gate SIGNED (100).

## Cumulative (v2.0.0 → v3.0.0)
Phase 2 (stateful/hardened/operable) at v2.0.0; Phase 3 (multi-tenant, observable, scaled,
accredited) landed across v2.1.0 and v3.0.0 — auth/clearance, DLP, dual-control θ promotion,
vLLM assist + entailment gate, Helm, Prometheus/Loki/alerts, DR active-active, engine
sharding, surrogate spike, caches, pilot kit, dissent, red-team exercise, learned analog
metric, ratchet gate, and the go-live governance above.

## Exit gate
`scripts/cut_release.sh --check` (v3.0.0): engine smoke, full suite, latency SLO, NLU-assist
p95, red-team gates, NLU contamination, ratchet regression, OpenAPI drift — all green. CI adds
test-pg, frontend, loadtest, helm, alerts (promtool), openapi, and the change-control gate.

## Cutting the tag
`VERSION` = 3.0.0 (single source of truth; read by the API + OpenAPI). Working tree not yet
under git; to tag:

```bash
scripts/cut_release.sh            # runs every gate, then tags v3.0.0 if a git repo
git add -A && git commit -m "ARGUS v3.0.0 — production go-live (100-task plan complete)"
git tag -a v3.0.0 -m "ARGUS v3.0.0 — production go-live"
```
