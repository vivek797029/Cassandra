"""Task 98 — performance freeze + cost/query model.

Estimates cost per query from right-sized infra (API replicas + optional GPU-backed
vLLM assist) amortized over throughput, with caching reducing the LLM-call fraction.
Used to verify the tuned configuration meets the cost/query target, and to show that
over-provisioning breaks it (so rightsizing matters).
"""
from __future__ import annotations

# illustrative on-demand unit prices
CPU_HOUR = 0.04      # $ / vCPU-hour
MEM_HOUR = 0.005     # $ / GiB-hour
GPU_HOUR = 1.50      # $ / GPU-hour (vLLM)
GPU_SECOND = GPU_HOUR / 3600.0

# tuned prod rightsizing (mirrors deploy/helm values-prod.yaml requests)
TUNED = {"replicas": 3, "cpu": 1.0, "mem": 2.0}
PILOT_QPS = 5000 / 86400.0     # ~5k queries/day (20-analyst pilot)
TARGET = 0.01                  # $ / query


def api_hourly(replicas: int, cpu: float, mem: float) -> float:
    return replicas * (cpu * CPU_HOUR + mem * MEM_HOUR)


def cost_per_query(qps: float, replicas: int = 3, cpu: float = 1.0, mem: float = 2.0,
                   llm_fraction: float = 0.15, gpu_seconds_per_call: float = 0.3,
                   cache_hit_rate: float = 0.6) -> float:
    """API infra amortized over throughput + pay-per-use GPU for the (cache-reduced)
    fraction of queries that actually invoke the LLM assist."""
    qph = qps * 3600.0
    if qph <= 0:
        return float("inf")
    api_amortized = api_hourly(replicas, cpu, mem) / qph
    effective_llm = llm_fraction * (1.0 - cache_hit_rate)   # cache cuts LLM calls
    llm_amortized = effective_llm * gpu_seconds_per_call * GPU_SECOND
    return round(api_amortized + llm_amortized, 6)


def report(qps: float = PILOT_QPS, target: float = TARGET, **tuning) -> dict:
    cfg = {**TUNED, **tuning}
    c = cost_per_query(qps, **cfg)
    return {"qps": round(qps, 4), "config": cfg, "cost_per_query": c,
            "target": target, "meets": c <= target}


if __name__ == "__main__":
    import json
    print(json.dumps({"tuned": report(),
                      "over_provisioned": report(replicas=20, cpu=4, mem=8)}, indent=2))
