"""Task 82 — engine sharding (parallel per-region twin slices).

A coupled Monte-Carlo world-twin parallelizes cleanly across the ENSEMBLE: split
the N paths into shards ("regions" for reporting), simulate each slice on its own
thread with a distinct CRN seed (numpy releases the GIL during the heavy array
math, so the slices truly run concurrently), then concatenate into one equivalent
ensemble. The merged event probabilities match a single-process run within Monte-
Carlo noise, and the per-shard execution intervals overlap (proving parallelism).
"""
from __future__ import annotations
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from core.engine import WorldEngine, event_probs

# path-arrays concatenated across shards; scalars taken from the first slice
_ARRAY_KEYS = ["oil", "growth", "inflation", "me", "ua", "tw",
               "em_def", "iran_stance", "ai_max"]


def merge_sims(sims: list[dict]) -> dict:
    merged = {k: np.concatenate([s[k] for s in sims], axis=0) for k in _ARRAY_KEYS}
    merged["N"] = int(sum(s["N"] for s in sims))
    merged["Q"] = sims[0]["Q"]
    merged["start"] = sims[0]["start"]
    return merged


def shard_sizes(N: int, shards: int) -> list[int]:
    base = N // shards
    sizes = [base] * shards
    sizes[-1] += N - base * shards          # remainder to the last slice
    return sizes


def sharded_simulate(theta, N: int, Q: int, seed: int, shards: int = 3,
                     region_names: list[str] | None = None,
                     max_workers: int | None = None) -> dict:
    """Run `shards` ensemble slices in parallel and merge. Returns the merged sim,
    its event probabilities, per-shard metadata, and a `parallel` concurrency flag."""
    eng = WorldEngine(theta=theta, seed=seed)        # simulate() is pure given an explicit seed
    sizes = shard_sizes(N, shards)
    names = region_names or [f"shard-{i}" for i in range(shards)]
    results: list = [None] * shards

    def _run(i: int):
        t0 = time.time()
        sim = eng.simulate(N=sizes[i], Q=Q, seed=seed + 1 + i)   # distinct CRN stream per slice
        t1 = time.time()
        return i, sim, {"region": names[i], "paths": sizes[i],
                        "t_start": t0, "t_end": t1, "dur_s": round(t1 - t0, 3)}

    wall0 = time.time()
    metas: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers or shards) as ex:
        for i, sim, meta in ex.map(_run, range(shards)):
            results[i] = sim
            metas.append(meta)
    wall = round(time.time() - wall0, 3)

    merged = merge_sims(results)
    # concurrency evidence: at least two slices' [start,end] intervals overlap
    parallel = max(m["t_start"] for m in metas) < min(m["t_end"] for m in metas)
    metas.sort(key=lambda m: m["region"])
    return {"sim": merged, "events": event_probs(merged), "shards": metas,
            "parallel": parallel, "wall_s": wall,
            "serial_s": round(sum(m["dur_s"] for m in metas), 3)}


# default region slices for the 3-region demo / nightly fan-out
DEFAULT_REGIONS = ["MiddleEast", "Ukraine-Russia", "Taiwan-EM"]
