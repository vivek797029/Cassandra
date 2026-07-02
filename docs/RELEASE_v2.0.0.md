# Release v2.0.0 — Phase-2 Exit Review

**Date:** 2026-06-22 · **Scope:** build-plan tasks 39–72 · **Changelog:** `CHANGELOG.md`
**Theme:** *Stateful, Hardened, Operable* — the Phase-1 prototype becomes a persistent,
ingestion-fed, adversarially hardened, operable service.

## Exit criteria

Each criterion has an owner gate; all are enforced in CI (`.github/workflows/ci.yml`).

| # | Criterion | Gate / evidence | Status |
|---|---|---|---|
| 1 | All Phase-2 tasks (39–72) complete | `docs/BUILD_PLAN.md` (39–72 all ✅) | ✅ |
| 2 | Full test suite green | `pytest tests/` → 92 passed, 1 PG-skip | ✅ |
| 3 | Backend parity (SQLite + PostgreSQL) | `test_store_contract.py` + CI `test-pg` (postgres:16) | ✅ |
| 4 | Latency SLOs | `benchmarks/bench_api.py` → ALL SLOs PASS | ✅ |
| 5 | Concurrency SLO (100 users) | `benchmarks/run_locust.py` → cached p99 36–62 ms, 0 failures | ✅ |
| 6 | θ-ball robustness | `tests/redteam/test_theta_ball.py` → flip 0/6 (≤ 2/6) | ✅ |
| 7 | No load-bearing feed (B8) | `tests/redteam/test_source_ablation.py` → max 0.083 (≤ 0.15) | ✅ |
| 8 | Prompt-injection grounding | `tests/redteam/test_injection.py` → 0 violations, 20/20 detected | ✅ |
| 9 | NLU contamination clean | `python -m services.copilot.nlu --gate` → canaries 10/10, injection 3/3 | ✅ |
| 10 | Graceful degradation | `tests/test_degradation.py` → cache + banner, 503 not 500, recovers | ✅ |
| 11 | Published API contract + no drift | `scripts/export_openapi.py --check` → v2.0.0, 31 paths, in sync | ✅ |
| 12 | Runbook + executed drills | `docs/RUNBOOK.md` + `test_runbook.py`; drills 2026-06-22 | ✅ |
| 13 | CI release gates wired | jobs: test, test-pg, frontend, loadtest, openapi, docker | ✅ |
| 14 | Version consistency | `VERSION` == app.version == OpenAPI version (`test_release.py`) | ✅ |

## Cutting the tag

`VERSION` is the single source of truth (the API and the OpenAPI artifact read it). Run the
release gate, then tag:

```bash
scripts/cut_release.sh            # runs every exit gate; tags v2.0.0 if a git repo
scripts/cut_release.sh --check    # gates only, no tag
```

This working tree is not yet under version control. To create the tag:

```bash
git init && git add -A && git commit -m "ARGUS v2.0.0 — Phase-2 exit"
git tag -a v2.0.0 -m "ARGUS v2.0.0 — Phase-2 exit (tasks 39–72)"
```

## Known limitations (carried into Phase 3)

From the blueprint risk register (§ "Known limitations"): the mechanism layer is still
expert-seeded (NMC arrives in Phase 2→3, Gen-1 inherits its authors' priors); ensemble
independence erodes under correlated upstream poisoning (B8 mitigates, does not cure);
conformal bands are a heuristic floor (exchangeability fails for world events). The Phase-3
program (Gen-2/Gen-3) replaces the slowest joints — see `docs/BLUEPRINT.md` §"Gen-2".

## Next

Task 73 closes Phase 2. The designated next deliverable is the research paper formalizing
B1–B8 and the Gen-3 program (blueprint epilogue), and the Phase-3 build block.
