# Performance Freeze + Cost Tuning (Task 98)

The performance-critical configuration is **frozen** at the tuned values below; changes
require change-control (Task 99). Model: `services/ops/cost_model.py`
(guard: `tests/test_cost.py`).

## Right-sizing (frozen)
| Component | Requests | Limits | Notes |
|-----------|----------|--------|-------|
| API (prod) | 1 vCPU / 2 GiB | 4 vCPU / 8 GiB | 3 replicas + HPA 3→12 @70% CPU (`values-prod.yaml`) |
| API (dev) | 250m / 512 MiB | 1 vCPU / 2 GiB | 1 replica, no HPA |
| Nightly jobs | 2 vCPU / 4 GiB | 4 vCPU / 8 GiB | pipeline / retrain / bands CronJobs |
| vLLM | GPU (scale-to-zero) | — | pay-per-use for NLU assist only |

## Cache TTLs (frozen)
| Cache | Backend | TTL / policy |
|-------|---------|--------------|
| Counterfactual (Task 85) | Redis / in-proc LRU | `ARGUS_CF_TTL` = 3600 s; LRU size `ARGUS_CF_CACHE_SIZE` = 256 |
| Full-fidelity bands (Task 83) | PostgreSQL | persistent, refreshed nightly |
| Baseline ensemble/forecasts | in-memory (per warm) | rebuilt on warm / snapshot |

## Cost model & target
`cost_per_query = api_infra_amortized_over_throughput + cache-reduced GPU-per-call`.

- **Target:** ≤ **$0.01 / query**.
- **Tuned (pilot ~5k queries/day):** ≈ **$0.0007 / query** → **MET**.
- **Over-provisioned (20 replicas, 4/8):** ≈ $0.019 / query → **fails** — right-sizing matters.
- Caching (Task 85) cuts the effective LLM-call fraction, lowering per-query cost.

## Freeze
This config is the baseline for the go-live (Task 100). Re-tune only via change-control
with a fresh `cost_model` report attached.
