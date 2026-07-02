"""Task 85 — counterfactual cache.

Counterfactual queries are pure given (interventions, hazard_mods, targets,
horizon, n_paths, theta) under common-random-number seeding, so identical do-clauses
can be memoized. Keyed by a stable clause hash; backed by Redis when `ARGUS_REDIS_URL`
is set, else an in-process LRU (so it works offline). A repeat counterfactual returns
in well under 10ms instead of re-running the paired simulation.
"""
from __future__ import annotations
import hashlib, json, copy
from collections import OrderedDict

from services.copilot.config import get_settings


def clause_key(interventions, hazard_mods, targets, horizon_q, n_paths, theta_hash) -> str:
    payload = {
        "iv": sorted(interventions or []),
        "hm": {k: round(float(v), 6) for k, v in sorted((hazard_mods or {}).items())},
        "tg": sorted(targets or []), "Q": horizon_q, "N": n_paths, "th": theta_hash,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


class _LRU:
    def __init__(self, size: int):
        self.size = max(1, size)
        self.d: OrderedDict = OrderedDict()

    def get(self, k):
        if k in self.d:
            self.d.move_to_end(k)
            return self.d[k]
        return None

    def set(self, k, v):
        self.d[k] = v
        self.d.move_to_end(k)
        while len(self.d) > self.size:
            self.d.popitem(last=False)


class _RedisBackend:
    def __init__(self, url: str, ttl: int = 3600):
        import redis
        self.r = redis.Redis.from_url(url)
        self.r.ping()
        self.ttl = ttl

    def get(self, k):
        v = self.r.get("cf:" + k)
        return json.loads(v) if v else None

    def set(self, k, v):
        self.r.set("cf:" + k, json.dumps(v), ex=self.ttl)


class CFCache:
    def __init__(self):
        s = get_settings()
        self.hits = 0
        self.misses = 0
        self.backend_name = "memory"
        self.backend = _LRU(s.cf_cache_size)
        if s.redis_url:
            try:
                self.backend = _RedisBackend(s.redis_url, ttl=s.cf_cache_ttl)
                self.backend_name = "redis"
            except Exception:
                pass                     # fall back to in-process LRU

    def get(self, key: str):
        v = self.backend.get(key)
        if v is None:
            self.misses += 1
            return None
        self.hits += 1
        return copy.deepcopy(v)          # isolate callers from the cached object

    def set(self, key: str, val: dict):
        self.backend.set(key, copy.deepcopy(val))

    def stats(self) -> dict:
        return {"backend": self.backend_name, "hits": self.hits, "misses": self.misses}


_CACHE: CFCache | None = None


def get_cf_cache() -> CFCache:
    global _CACHE
    if _CACHE is None:
        _CACHE = CFCache()
    return _CACHE


def reset_cf_cache() -> None:
    global _CACHE
    _CACHE = None
